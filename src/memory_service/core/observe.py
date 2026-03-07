"""Core observe logic — short-term first, background hydration.

Shared between REST and gRPC observe endpoints.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List
from uuid import uuid4

from ..smart.judge_observation import judge_observation

logger = logging.getLogger(__name__)

# Retrieval parameters for FalkorDB searches (used in background hydration + cold start)
RETRIEVAL_PARAMS = {"top_k": 25, "min_score": 0.40}
KNOWLEDGE_PARAMS = {"top_k": 10, "min_score": 0.40}

_PROPER_NOUN_SKIP = {
    "What", "When", "Where", "Who", "How", "Why", "Which", "Does", "Did",
    "Has", "Have", "Had", "Was", "Were", "Are", "Is", "Can", "Could",
    "Would", "Should", "Will", "The", "This", "That", "These", "Those",
    "And", "But", "For", "Not", "Yes", "No", "According",
}


def _extract_proper_nouns(text: str) -> List[str]:
    """Extract proper nouns from text using regex heuristics."""
    words = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text)
    return [w for w in words if w not in _PROPER_NOUN_SKIP and len(w) > 1]


def _merge_entity_results(
    episodes: List[Dict[str, Any]],
    entity_episodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge entity search results: boost overlaps +0.1, add new at 0.7x."""
    existing = {ep.get("uuid"): ep for ep in episodes}
    for ent_ep in entity_episodes:
        uuid = ent_ep.get("uuid")
        if uuid in existing:
            existing[uuid]["score"] = existing[uuid].get("score", 0) + 0.1
        else:
            ent_ep["score"] = ent_ep.get("score", 0.5) * 0.7
            episodes.append(ent_ep)
    episodes.sort(key=lambda x: x.get("score", 0), reverse=True)
    return episodes


async def enrich_with_entities(
    episode_store, content: str, ep_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract proper nouns and merge entity search results."""
    proper_nouns = _extract_proper_nouns(content)
    if not proper_nouns:
        return ep_results
    try:
        entity_eps = await episode_store.search_by_entities(
            entity_names=proper_nouns, top_k=10,
        )
        return _merge_entity_results(ep_results, entity_eps)
    except Exception:
        return ep_results


async def background_hydrate(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    embedding: List[float],
    metadata: dict,
    episode_uuid: str,
):
    """Background: store in FalkorDB, search, hydrate DragonflyDB session, run judge."""
    try:
        # 1. Store in FalkorDB (long-term)
        try:
            await episode_store._store_with_embedding(
                content=content,
                embedding=embedding,
                metadata=metadata,
                episode_type="raw",
                auto_link=True,
                episode_uuid=episode_uuid,
            )
        except Exception as e:
            logger.warning(f"FalkorDB store failed: {e}")

        # 2. Search FalkorDB for related context (with embeddings for hydration)
        ep_results, kn_results = await asyncio.gather(
            episode_store._search_with_embedding(
                embedding=embedding,
                top_k=RETRIEVAL_PARAMS["top_k"],
                min_score=RETRIEVAL_PARAMS["min_score"],
                expand_adjacent=True,
                expansion_hops=1,
                include_embedding=True,
            ),
            knowledge_store.search_hybrid(
                query=content,
                top_k=KNOWLEDGE_PARAMS["top_k"],
                min_score=KNOWLEDGE_PARAMS["min_score"],
            ),
        )

        # 3. Entity search
        ep_results = await enrich_with_entities(episode_store, content, ep_results)

        # 3b. Hebbian reinforcement (fire-and-forget background task)
        from ..config import (
            get_hebbian_enabled, get_hebbian_learning_rate,
            get_hebbian_max_pairs, get_hebbian_activation_cap,
        )
        if get_hebbian_enabled():
            from .hebbian import (
                reinforce_co_activations, reinforce_knowledge_activations,
            )
            ep_uuids = [
                r["uuid"] for r in ep_results
                if r.get("uuid") and r["uuid"] != episode_uuid
            ]
            if ep_uuids:
                asyncio.create_task(reinforce_co_activations(
                    graph=episode_store._graph,
                    trigger_uuid=episode_uuid,
                    result_uuids=ep_uuids,
                    learning_rate=get_hebbian_learning_rate(),
                    max_pairs=get_hebbian_max_pairs(),
                    activation_cap=get_hebbian_activation_cap(),
                ))
            kn_uuids = [r["uuid"] for r in kn_results if r.get("uuid")]
            if kn_uuids:
                asyncio.create_task(reinforce_knowledge_activations(
                    graph=episode_store._graph,
                    result_uuids=kn_uuids,
                    activation_cap=get_hebbian_activation_cap(),
                ))

        # 4. Hydrate DragonflyDB session with episode results (deduplicated)
        #    Sort candidates by recency — inject most recent semantically-relevant
        #    items first (semantic quality already guaranteed by min_score filter).
        hydration_candidates = sorted(
            ep_results[:30],
            key=lambda x: x.get("created_at", 0),
            reverse=True,
        )

        hydrated = 0
        for ep in hydration_candidates:
            if hydrated >= 15:
                break
            ep_uuid = ep.get("uuid", "")
            if not ep_uuid or ep_uuid == episode_uuid:
                continue
            # Skip near-exact matches (same content stored under different UUID)
            if ep.get("_semantic_score", ep.get("score", 0)) > 0.99:
                continue
            if await dragonfly.session_has(session_id, ep_uuid):
                continue
            ep_embedding = ep.get("embedding")
            if not ep_embedding:
                try:
                    ep_embedding = await episode_store._embed(ep["content"])
                except Exception:
                    continue
            try:
                await dragonfly.session_add(
                    session_id, ep_uuid, ep["content"],
                    ep_embedding, ep.get("metadata", {}),
                    source_type="hydrated",
                )
                hydrated += 1
            except Exception:
                pass

        # 5. Hydrate knowledge entries into session
        for kn in kn_results[:10]:
            kn_uuid = kn.get("uuid", "")
            kn_id = f"kn_{kn_uuid}" if kn_uuid else ""
            if not kn_id:
                continue
            if await dragonfly.session_has(session_id, kn_id):
                continue
            kn_content = kn.get("content", "")
            if not kn_content:
                continue
            try:
                kn_embedding = await episode_store._embed(kn_content)
                await dragonfly.session_add(
                    session_id, kn_id, kn_content,
                    kn_embedding, {"knowledge_type": kn.get("type", "")},
                    source_type="hydrated_knowledge",
                )
                hydrated += 1
            except Exception:
                pass

        logger.info(
            f"Hydration done: {hydrated} entries added to session {session_id[:8]}, "
            f"episodes={len(ep_results)}, knowledge={len(kn_results)}"
        )

        # 6. Run judge
        try:
            judge_result = await judge_observation(
                content=content, source=metadata.get("source", ""),
            )
            logger.info(
                f"Judge done: uuid={episode_uuid[:8]}, "
                f"type={judge_result['observation_type']}, "
                f"importance={judge_result['importance']}"
            )
        except Exception as e:
            logger.warning(f"Background judge failed: {e}")

    except Exception as e:
        logger.error(f"Background hydration error: {e}", exc_info=True)


async def observe_core(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    timestamp: str = None,
    source: str = None,
    metadata: dict = None,
) -> dict:
    """Core observe logic — short-term first, background hydration.

    Returns dict with keys: episode_uuid, observation_type, context,
    is_cold, session_episodes (list of episode dicts), knowledge (list).
    """
    # Map session_id to internal scope
    episode_store._group_id = session_id
    knowledge_store._group_id = session_id

    # Inject timestamp into metadata if provided
    metadata = dict(metadata or {})
    if timestamp:
        metadata["date_time"] = timestamp
    if source:
        metadata["source"] = source

    # Step 1: Embed content
    embedding = await episode_store._embed(content)
    episode_uuid = str(uuid4())

    # Step 2: Store in DragonflyDB session
    await dragonfly.session_add(
        session_id=session_id,
        entry_uuid=episode_uuid,
        content=content,
        embedding=embedding,
        metadata=metadata,
        source_type="local",
    )

    # Step 3: Check cold start
    session_entry_count = await dragonfly.session_count(session_id)
    is_cold = session_entry_count < 2

    if is_cold:
        # Cold start — synchronous FalkorDB search for initial context
        logger.info(f"Cold start for session {session_id[:8]}, sync FalkorDB search")
        ep_results, kn_results = await asyncio.gather(
            episode_store._search_with_embedding(
                embedding=embedding,
                top_k=RETRIEVAL_PARAMS["top_k"],
                min_score=RETRIEVAL_PARAMS["min_score"],
                expand_adjacent=True,
                expansion_hops=1,
            ),
            knowledge_store.search_hybrid(
                query=content,
                top_k=KNOWLEDGE_PARAMS["top_k"],
                min_score=KNOWLEDGE_PARAMS["min_score"],
            ),
        )

        # Entity search
        ep_results = await enrich_with_entities(episode_store, content, ep_results)

        context = {
            "episodes": ep_results,
            "knowledge": kn_results,
        }
    else:
        # Step 4: Warm session — search DragonflyDB only
        session_results = await dragonfly.session_search(
            session_id=session_id,
            query_embedding=embedding,
            top_k=RETRIEVAL_PARAMS["top_k"],
            min_score=RETRIEVAL_PARAMS["min_score"],
        )

        # Filter out the just-stored entry
        session_results = [r for r in session_results if r.get("uuid") != episode_uuid]

        context = {
            "episodes": session_results,
            "knowledge": [],
        }

    # Step 5: Fire background hydration
    asyncio.create_task(background_hydrate(
        episode_store, knowledge_store, dragonfly,
        session_id, content, embedding,
        metadata, episode_uuid,
    ))

    logger.info(
        f"Observe done: session={session_id[:8]}, uuid={episode_uuid[:8]}, "
        f"cold={is_cold}, context_episodes={len(context['episodes'])}"
    )

    return {
        "episode_uuid": episode_uuid,
        "observation_type": "observe",
        "context": context,
        "is_cold": is_cold,
    }
