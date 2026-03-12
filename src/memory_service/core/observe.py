"""Core observe logic — short-term first, background hydration.

Shared between REST and gRPC observe endpoints.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..config import (
    get_episode_alpha, get_episode_half_life,
    get_hebbian_activation_cap, get_hebbian_beta_episode,
    get_hebbian_enabled, get_hebbian_learning_rate, get_hebbian_max_pairs,
)
from ..smart.judge_observation import judge_observation

logger = logging.getLogger(__name__)

# Retrieval parameters
RETRIEVAL_PARAMS = {"top_k": 25, "min_score": 0.40}
KNOWLEDGE_PARAMS = {"top_k": 10, "min_score": 0.40}

_PROPER_NOUN_SKIP = {
    "What", "When", "Where", "Who", "How", "Why", "Which", "Does", "Did",
    "Has", "Have", "Had", "Was", "Were", "Are", "Is", "Can", "Could",
    "Would", "Should", "Will", "The", "This", "That", "These", "Those",
    "And", "But", "For", "Not", "Yes", "No", "According",
}


# ── Helpers ──────────────────────────────────────────────────────────


def _extract_proper_nouns(text: str) -> List[str]:
    words = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text)
    return [w for w in words if w not in _PROPER_NOUN_SKIP and len(w) > 1]


async def _enrich_with_entities(
    episode_store, content: str, episodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge entity search results into episode list."""
    proper_nouns = _extract_proper_nouns(content)
    if not proper_nouns:
        return episodes
    try:
        entity_eps = await episode_store.search_by_entities(
            entity_names=proper_nouns, top_k=10,
        )
        existing = {ep.get("uuid"): ep for ep in episodes}
        for ent_ep in entity_eps:
            uuid = ent_ep.get("uuid")
            if uuid in existing:
                existing[uuid]["score"] = existing[uuid].get("score", 0) + 0.1
            else:
                ent_ep["score"] = ent_ep.get("score", 0.5) * 0.7
                episodes.append(ent_ep)
        episodes.sort(key=lambda x: x.get("score", 0), reverse=True)
    except Exception:
        pass
    return episodes


async def _score_3dim(
    episode_store, episodes: List[Dict[str, Any]], episode_uuid: str,
    alpha: float, half_life: float,
) -> List[Dict[str, Any]]:
    """Apply scoring: 3-dim (semantic + temporal + Hebbian) or 2-dim fallback."""
    if not episodes:
        return episodes

    from ..scoring import apply_temporal_score

    if not get_hebbian_enabled():
        return apply_temporal_score(
            results=episodes, alpha=alpha, half_life_hours=half_life,
        )

    from .hebbian import get_co_activation_weights
    from ..scoring import apply_hebbian_score

    uuids = [r["uuid"] for r in episodes if r.get("uuid")]
    co_weights = await get_co_activation_weights(
        graph=episode_store._graph,
        trigger_uuid=episode_uuid,
        result_uuids=uuids,
    )
    return apply_hebbian_score(
        results=episodes,
        beta=get_hebbian_beta_episode(),
        alpha=alpha,
        half_life_hours=half_life,
        max_activation_count=get_hebbian_activation_cap(),
        co_activation_weights=co_weights,
    )


async def _hydrate_episodes(
    episode_store, dragonfly, session_id: str,
    episodes: List[Dict[str, Any]], episode_uuid: str,
    max_items: int = 15,
) -> int:
    """Write episodes to DragonflyDB session, deduplicating."""
    hydrated = 0
    for ep in episodes:
        if hydrated >= max_items:
            break
        ep_uuid = ep.get("uuid", "")
        if not ep_uuid or ep_uuid == episode_uuid:
            continue
        if ep.get("_semantic_score", ep.get("score", 0)) > 0.99:
            continue
        if await dragonfly.session_has(session_id, ep_uuid):
            continue
        ep_emb = ep.get("embedding")
        if not ep_emb:
            try:
                ep_emb = await episode_store._embed(ep["content"])
            except Exception:
                continue
        try:
            ep_meta = {**ep.get("metadata", {})}
            if ep.get("episode_type"):
                ep_meta["episode_type"] = ep["episode_type"]
            await dragonfly.session_add(
                session_id, ep_uuid, ep["content"],
                ep_emb, ep_meta,
                source_type="hydrated",
            )
            hydrated += 1
        except Exception:
            pass
    return hydrated


async def _hydrate_knowledge(
    episode_store, dragonfly, session_id: str,
    knowledge: List[Dict[str, Any]],
    max_items: int = 10,
) -> int:
    """Write knowledge entries to DragonflyDB session."""
    hydrated = 0
    for kn in knowledge[:max_items]:
        kn_uuid = kn.get("uuid", "")
        if not kn_uuid:
            continue
        kn_id = f"kn_{kn_uuid}"
        if await dragonfly.session_has(session_id, kn_id):
            continue
        kn_content = kn.get("content", "")
        if not kn_content:
            continue
        try:
            kn_emb = await episode_store._embed(kn_content)
            await dragonfly.session_add(
                session_id, kn_id, kn_content,
                kn_emb, {"knowledge_type": kn.get("type", "")},
                source_type="hydrated_knowledge",
            )
            hydrated += 1
        except Exception:
            pass
    return hydrated


async def _search_falkordb(
    episode_store, knowledge_store, query: str,
    embedding: List[float], episode_uuid: str,
    labels: Optional[List[str]] = None,
    entity_content: Optional[str] = None,
) -> tuple:
    """Search FalkorDB for episodes + knowledge, enrich with entities, score 3-dim.

    Args:
        query: Search query text (may be reinterpreted on cold start).
        entity_content: Raw observation text for proper noun extraction.
                        Defaults to query if not provided.
    """
    kn_kwargs = {
        "query": query,
        "top_k": KNOWLEDGE_PARAMS["top_k"],
        "min_score": KNOWLEDGE_PARAMS["min_score"],
    }
    if labels:
        kn_kwargs["labels"] = labels

    episodes, knowledge = await asyncio.gather(
        episode_store._search_with_embedding(
            embedding=embedding,
            top_k=RETRIEVAL_PARAMS["top_k"],
            min_score=RETRIEVAL_PARAMS["min_score"],
            expand_adjacent=True,
            expansion_hops=1,
            include_embedding=True,
        ),
        knowledge_store.search_hybrid(**kn_kwargs),
    )

    episodes = await _enrich_with_entities(
        episode_store, entity_content or query, episodes,
    )
    episodes = await _score_3dim(
        episode_store, episodes, episode_uuid,
        alpha=get_episode_alpha(),
        half_life=get_episode_half_life(),
    )

    return episodes, knowledge


async def _reinforce_hebbian(episode_store, episode_uuid: str, episodes, knowledge):
    """Fire-and-forget Hebbian reinforcement."""
    if not get_hebbian_enabled() or not episodes:
        return

    from .hebbian import reinforce_co_activations, reinforce_knowledge_activations

    ep_uuids = [r["uuid"] for r in episodes if r.get("uuid") and r["uuid"] != episode_uuid]
    if ep_uuids:
        asyncio.create_task(reinforce_co_activations(
            graph=episode_store._graph,
            trigger_uuid=episode_uuid,
            result_uuids=ep_uuids,
            learning_rate=get_hebbian_learning_rate(),
            max_pairs=get_hebbian_max_pairs(),
            activation_cap=get_hebbian_activation_cap(),
        ))

    kn_uuids = [r["uuid"] for r in knowledge if r.get("uuid")]
    if kn_uuids:
        asyncio.create_task(reinforce_knowledge_activations(
            graph=episode_store._graph,
            result_uuids=kn_uuids,
            activation_cap=get_hebbian_activation_cap(),
        ))


# ── Background ───────────────────────────────────────────────────────


async def background_hydrate(
    episode_store, knowledge_store, dragonfly,
    session_id: str, content: str, embedding: List[float],
    metadata: dict, episode_uuid: str,
    prefill_episodes: List[Dict[str, Any]] = None,
    prefill_knowledge: List[Dict[str, Any]] = None,
):
    """Background: store in FalkorDB, hydrate (warm), Hebbian reinforce, judge."""
    try:
        # 1. Store in FalkorDB
        try:
            await episode_store._store_with_embedding(
                content=content, embedding=embedding, metadata=metadata,
                episode_type="raw", auto_link=True, episode_uuid=episode_uuid,
            )
        except Exception as e:
            logger.warning(f"FalkorDB store failed: {e}")

        # 2. Get episodes + knowledge (cold: reuse pre-fill, warm: search + hydrate)
        if prefill_episodes is not None:
            episodes = prefill_episodes
            knowledge = prefill_knowledge or []
        else:
            episodes, knowledge = await _search_falkordb(
                episode_store, knowledge_store, content,
                embedding, episode_uuid,
            )
            ep_count = await _hydrate_episodes(
                episode_store, dragonfly, session_id, episodes, episode_uuid,
            )
            kn_count = await _hydrate_knowledge(
                episode_store, dragonfly, session_id, knowledge,
            )
            logger.info(
                f"Hydration done: {ep_count + kn_count} entries added to "
                f"session {session_id[:8]}"
            )

        # 3. Hebbian reinforcement
        await _reinforce_hebbian(episode_store, episode_uuid, episodes, knowledge)

        # 4. Judge
        try:
            judge_result = await judge_observation(
                content=content, source=metadata.get("source", ""),
            )
            logger.info(
                f"Judge: uuid={episode_uuid[:8]}, "
                f"type={judge_result['observation_type']}, "
                f"importance={judge_result['importance']}"
            )
        except Exception as e:
            logger.warning(f"Background judge failed: {e}")

    except Exception as e:
        logger.error(f"Background hydration error: {e}", exc_info=True)


# ── Main entry point ─────────────────────────────────────────────────


async def observe_core(
    episode_store, knowledge_store, dragonfly,
    session_id: str, content: str,
    timestamp: str = None, source: str = None, metadata: dict = None,
    read_only: bool = False,
    summarize: bool = False,
    top_k: int = 10,
    knowledge_top_k: int = 10,
) -> dict:
    """Core observe logic — store, summarize, return context.

    Cold start: reinterpret → FalkorDB search → pre-fill DragonflyDB.
    Warm: DragonflyDB already populated by background hydration.
    Both paths converge: add to DragonflyDB → LLM summarize session → return.

    If read_only=True, skip all writes and use the warm path summarization only.
    """
    # Scope
    episode_store._group_id = session_id
    knowledge_store._group_id = session_id

    metadata = dict(metadata or {})
    if timestamp:
        metadata["date_time"] = timestamp
    if source:
        metadata["source"] = source

    episode_uuid = ""
    search_labels = []
    search_query = content
    is_cold = False
    falkor_episodes = None
    falkor_knowledge = None

    if not read_only:
        # Step 1: Embed + store in DragonflyDB
        try:
            embedding = await episode_store._embed(content)
        except Exception as e:
            logger.warning(f"Embedding failed, returning empty context: {e}")
            return {
                "episode_uuid": str(uuid4()),
                "observation_type": "observe",
                "context": "",
                "is_cold": False,
                "search_labels": [],
                "search_query": "",
            }
        episode_uuid = str(uuid4())

        await dragonfly.session_add(
            session_id=session_id, entry_uuid=episode_uuid,
            content=content, embedding=embedding,
            metadata=metadata, source_type="local",
        )

        # Step 2: Cold start pre-fill
        session_entry_count = await dragonfly.session_count(session_id)
        is_cold = session_entry_count < 2
        search_embedding = embedding

        if is_cold:
            logger.info(f"Cold start for session {session_id[:8]}")

            # Reinterpret content for optimized search
            try:
                from ..smart.reinterpret import reinterpret_task
                reinterpretation = await reinterpret_task(task=content)
                search_labels = reinterpretation.get("search_labels", [])
                search_query = reinterpretation.get("search_query", content)
            except Exception as e:
                logger.warning(f"Reinterpret failed: {e}")

            # Embed optimized query
            if search_query != content:
                search_embedding = await episode_store._embed(search_query)

            # Search FalkorDB + score + enrich
            falkor_episodes, falkor_knowledge = await _search_falkordb(
                episode_store, knowledge_store, search_query,
                search_embedding, episode_uuid, labels=search_labels,
                entity_content=content,
            )

            # Pre-fill DragonflyDB
            ep_count = await _hydrate_episodes(
                episode_store, dragonfly, session_id,
                falkor_episodes, episode_uuid,
            )
            kn_count = await _hydrate_knowledge(
                episode_store, dragonfly, session_id, falkor_knowledge,
            )
            logger.info(f"Pre-filled: {ep_count} episodes, {kn_count} knowledge")

    # Step 3: Get session entries — use 3D scoring (semantic + temporal + Hebbian)
    # instead of recency cap so the most relevant entries survive, not the most recent.
    # read_only: embed here (cheap; LLM summarization is already skipped by default).
    if read_only and not locals().get("embedding"):
        try:
            embedding = await episode_store._embed(content)
        except Exception as e:
            logger.warning(f"Embedding failed in read_only: {e}")
            embedding = None

    if embedding is not None:
        # Semantic search within session → top 100 by cosine similarity
        search_results = await dragonfly.session_search(
            session_id=session_id,
            query_embedding=embedding,
            top_k=top_k,
            min_score=0.0,
        )
        if episode_uuid:
            search_results = [r for r in search_results if r.get("uuid") != episode_uuid]

        # Apply 3D scoring: semantic + temporal + Hebbian
        search_results = await _score_3dim(
            episode_store, search_results, episode_uuid,
            alpha=get_episode_alpha(),
            half_life=get_episode_half_life(),
        )
        entries = {r["uuid"]: r for r in search_results}
    else:
        # Fallback: recency cap (no embedding available)
        entries = await dragonfly.session_get_all(session_id)
        if episode_uuid:
            entries.pop(episode_uuid, None)
        if len(entries) > top_k:
            sorted_items = sorted(entries.items(), key=lambda x: x[1].get("created_at", 0), reverse=True)
            entries = dict(sorted_items[:top_k])

    # read_only: augment with a fresh synchronous knowledge search from FalkorDB.
    # The warm session only has knowledge cached from ingest time; this brings in
    # knowledge specifically relevant to the current question.
    if read_only:
        try:
            kn_results = await knowledge_store.search_hybrid(
                query=content,
                top_k=knowledge_top_k,
                min_score=KNOWLEDGE_PARAMS["min_score"],
            )
            for kn in kn_results:
                kn_uuid = kn.get("uuid", "")
                key = f"kn_{kn_uuid}"
                if kn_uuid and key not in entries:
                    entries[key] = {
                        "content": kn.get("content", ""),
                        "source_type": "hydrated_knowledge",
                        "created_at": 0,
                    }
        except Exception as e:
            logger.warning(f"read_only knowledge search failed: {e}")

    context = ""
    if entries:
        if summarize:
            from ..smart.summarize_context import summarize_context
            context = await summarize_context(
                current_observation=content,
                session_entries=entries,
            )
        else:
            from ..smart.summarize_context import _format_entries
            context = _format_entries(entries)

    if not read_only:
        # Step 4: Fire background
        asyncio.create_task(background_hydrate(
            episode_store, knowledge_store, dragonfly,
            session_id, content, embedding, metadata, episode_uuid,
            prefill_episodes=falkor_episodes if is_cold else None,
            prefill_knowledge=falkor_knowledge if is_cold else None,
        ))

    logger.info(
        f"Observe done: session={session_id[:8]}, "
        f"{'read_only' if read_only else f'uuid={episode_uuid[:8]}'}, "
        f"cold={is_cold}, entries={len(entries)}"
    )

    return {
        "episode_uuid": episode_uuid,
        "observation_type": "observe",
        "context": context,
        "is_cold": is_cold,
        "search_labels": search_labels,
        "search_query": search_query,
    }
