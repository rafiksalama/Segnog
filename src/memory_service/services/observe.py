"""Core observe logic — short-term first, background hydration.

Shared between REST and gRPC observe endpoints.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..config import (
    get_episode_alpha,
    get_episode_half_life,
    get_hebbian_activation_cap,
    get_hebbian_beta_episode,
    get_hebbian_enabled,
    get_hebbian_learning_rate,
    get_hebbian_max_pairs,
    get_retrieval_episode_top_k,
    get_retrieval_knowledge_top_k,
    get_retrieval_min_score,
    get_retrieval_ontology_min_score,
)
from ..intelligence.evaluation.judge_observation import judge_observation
from .task_registry import PipelineConfig, load_pipeline_config

logger = logging.getLogger(__name__)


def _retrieval_params() -> dict:
    return {"top_k": get_retrieval_episode_top_k(), "min_score": get_retrieval_min_score()}


def _knowledge_params() -> dict:
    return {"top_k": get_retrieval_knowledge_top_k(), "min_score": get_retrieval_min_score()}


_PROPER_NOUN_SKIP = {
    "What",
    "When",
    "Where",
    "Who",
    "How",
    "Why",
    "Which",
    "Does",
    "Did",
    "Has",
    "Have",
    "Had",
    "Was",
    "Were",
    "Are",
    "Is",
    "Can",
    "Could",
    "Would",
    "Should",
    "Will",
    "The",
    "This",
    "That",
    "These",
    "Those",
    "And",
    "But",
    "For",
    "Not",
    "Yes",
    "No",
    "According",
}


# ── Helpers ──────────────────────────────────────────────────────────


async def _get_recent_episodes(episode_store, n: int = 1) -> List[Dict[str, Any]]:
    """Get the N most recent raw episodes for the current group from FalkorDB."""
    try:
        # FalkorDB does not support parameterised LIMIT — embed n directly.
        cypher = (
            f"MATCH (e:Episode {{group_id: $gid, episode_type: 'raw'}}) "
            f"RETURN e.uuid, e.content, e.created_at, e.created_at_iso "
            f"ORDER BY e.created_at DESC LIMIT {int(n)}"
        )
        result = await episode_store._graph.query(cypher, params={"gid": episode_store._group_id})
        episodes = []
        for row in result.result_set:
            episodes.append(
                {
                    "uuid": row[0] or "",
                    "content": row[1] or "",
                    "created_at": row[2] or 0,
                    "created_at_iso": row[3] or "",
                    "source_type": "recent_episode",
                }
            )
        return episodes
    except Exception as e:
        logger.warning(f"_get_recent_episodes failed: {e}")
        return []


def _extract_proper_nouns(text: str) -> List[str]:
    words = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text)
    return [w for w in words if w not in _PROPER_NOUN_SKIP and len(w) > 1]


async def _enrich_with_entities(
    episode_store,
    content: str,
    episodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge entity search results into episode list."""
    proper_nouns = _extract_proper_nouns(content)
    if not proper_nouns:
        return episodes
    try:
        entity_eps = await episode_store.search_by_entities(
            entity_names=proper_nouns,
            top_k=10,
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
    except Exception as e:
        logger.warning(f"Entity enrichment failed: {e}")
    return episodes


async def _score_3dim(
    episode_store,
    episodes: List[Dict[str, Any]],
    episode_uuid: str,
    alpha: float,
    half_life: float,
) -> List[Dict[str, Any]]:
    """Apply scoring: 3-dim (semantic + temporal + Hebbian) or 2-dim fallback."""
    if not episodes:
        return episodes

    from ..storage.retrieval.scoring import apply_temporal_score

    if not get_hebbian_enabled():
        return apply_temporal_score(
            results=episodes,
            alpha=alpha,
            half_life_hours=half_life,
        )

    from ..storage.retrieval.hebbian import get_co_activation_weights
    from ..storage.retrieval.scoring import apply_hebbian_score

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
    episode_store,
    dragonfly,
    session_id: str,
    episodes: List[Dict[str, Any]],
    episode_uuid: str,
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
            except Exception as e:
                logger.warning(f"Episode embed failed during hydration: {e}")
                continue
        try:
            ep_meta = {**ep.get("metadata", {})}
            if ep.get("episode_type"):
                ep_meta["episode_type"] = ep["episode_type"]
            await dragonfly.session_add(
                session_id,
                ep_uuid,
                ep["content"],
                ep_emb,
                ep_meta,
                source_type="hydrated",
            )
            hydrated += 1
        except Exception as e:
            logger.warning(f"Episode session_add failed during hydration: {e}")
    return hydrated


async def _hydrate_knowledge(
    episode_store,
    dragonfly,
    session_id: str,
    knowledge: List[Dict[str, Any]],
    max_items: int = 10,
) -> int:
    """Write knowledge entries to DragonflyDB session, reusing stored embeddings."""
    # Filter to items needing hydration
    to_hydrate = []
    for kn in knowledge[:max_items]:
        kn_uuid = kn.get("uuid", "")
        if not kn_uuid or not kn.get("content", ""):
            continue
        kn_id = f"kn_{kn_uuid}"
        if not await dragonfly.session_has(session_id, kn_id):
            to_hydrate.append((kn_id, kn))

    if not to_hydrate:
        return 0

    # Embed only entries missing stored embeddings — in one batch call
    needs_embed = [(kid, kn) for kid, kn in to_hydrate if not kn.get("embedding")]
    if needs_embed:
        try:
            batch_embs = await episode_store._embed_batch([kn["content"] for _, kn in needs_embed])
            for (kid, kn), emb in zip(needs_embed, batch_embs):
                kn["embedding"] = emb
        except Exception as e:
            logger.warning(
                f"Knowledge batch embed failed during hydration: {e}"
            )  # entries without embeddings will be skipped below

    hydrated = 0
    for kn_id, kn in to_hydrate:
        emb = kn.get("embedding")
        if not emb:
            continue
        try:
            await dragonfly.session_add(
                session_id,
                kn_id,
                kn["content"],
                emb,
                {"knowledge_type": kn.get("type", kn.get("knowledge_type", ""))},
                source_type="hydrated_knowledge",
            )
            hydrated += 1
        except Exception as e:
            logger.warning(f"Knowledge session_add failed during hydration: {e}")
    return hydrated


async def _hydrate_ontology_nodes(
    episode_store,
    dragonfly,
    session_id: str,
    onto_nodes: List[Dict[str, Any]],
    max_items: int = 5,
) -> int:
    """Write OntologyNode summaries to DragonflyDB session, reusing stored embeddings."""
    # Filter to items needing hydration and build content strings
    to_hydrate = []
    for node in onto_nodes[:max_items]:
        node_uuid = node.get("uuid", "")
        summary = node.get("summary", "")
        if not node_uuid or not summary:
            continue
        key = f"onto_{node_uuid}"
        if await dragonfly.session_has(session_id, key):
            continue
        display = node.get("display_name") or node.get("name", "")
        content = f"{display}: {summary}" if display else summary
        to_hydrate.append((key, content, node.get("embedding")))

    if not to_hydrate:
        return 0

    # Embed only entries missing stored embeddings — in one batch call
    needs_embed = [(i, key, content) for i, (key, content, emb) in enumerate(to_hydrate) if not emb]
    if needs_embed:
        try:
            batch_embs = await episode_store._embed_batch(
                [content for _, _, content in needs_embed]
            )
            to_hydrate = list(to_hydrate)
            for (i, key, content), emb in zip(needs_embed, batch_embs):
                to_hydrate[i] = (key, content, emb)
        except Exception as e:
            logger.warning(
                f"Ontology batch embed failed during hydration: {e}"
            )  # entries without embeddings will be skipped below

    hydrated = 0
    for key, content, emb in to_hydrate:
        if not emb:
            continue
        try:
            await dragonfly.session_add(
                session_id,
                key,
                content,
                emb,
                {},
                source_type="ontology_node",
            )
            hydrated += 1
        except Exception as e:
            logger.warning(f"Ontology session_add failed during hydration: {e}")
    return hydrated


async def _search_and_hydrate_ontology(
    ontology_store,
    episode_store,
    dragonfly,
    session_id: str,
    embedding: List[float],
    ontology_top_k: int,
    pipeline: PipelineConfig,
    log_prefix: str = "Ontology hydration",
) -> int:
    """Search OntologyStore and hydrate DragonflyDB session. Returns count hydrated."""
    if ontology_store is None or not pipeline.hydrate_ontology:
        return 0
    try:
        onto_nodes = await ontology_store.search_nodes(
            embedding=embedding,
            top_k=ontology_top_k,
            group_id=session_id,
            min_score=get_retrieval_ontology_min_score(),
            include_embedding=True,
        )
        return await _hydrate_ontology_nodes(episode_store, dragonfly, session_id, onto_nodes)
    except Exception as e:
        logger.warning(f"{log_prefix} failed: {e}")
        return 0


async def _search_falkordb(
    episode_store,
    knowledge_store,
    query: str,
    embedding: List[float],
    episode_uuid: str,
    labels: Optional[List[str]] = None,
    entity_content: Optional[str] = None,
) -> tuple:
    """Search FalkorDB for episodes + knowledge, enrich with entities, score 3-dim.

    Args:
        query: Search query text (may be reinterpreted on cold start).
        entity_content: Raw observation text for proper noun extraction.
                        Defaults to query if not provided.
    """
    kn_p = _knowledge_params()
    kn_kwargs = {
        "query": query,
        "top_k": kn_p["top_k"],
        "min_score": kn_p["min_score"],
    }
    if labels:
        kn_kwargs["labels"] = labels

    ret_p = _retrieval_params()
    episodes, knowledge = await asyncio.gather(
        episode_store._search_with_embedding(
            embedding=embedding,
            top_k=ret_p["top_k"],
            min_score=ret_p["min_score"],
            expand_adjacent=True,
            expansion_hops=1,
            include_embedding=True,
        ),
        knowledge_store.search_hybrid(**kn_kwargs, include_embedding=True),
    )

    episodes = await _enrich_with_entities(
        episode_store,
        entity_content or query,
        episodes,
    )
    episodes = await _score_3dim(
        episode_store,
        episodes,
        episode_uuid,
        alpha=get_episode_alpha(),
        half_life=get_episode_half_life(),
    )

    return episodes, knowledge


async def _reinforce_hebbian(episode_store, episode_uuid: str, episodes, knowledge):
    """Fire-and-forget Hebbian reinforcement."""
    if not get_hebbian_enabled() or not episodes:
        return

    from ..storage.retrieval.hebbian import (
        reinforce_co_activations,
        reinforce_knowledge_activations,
    )

    ep_uuids = [r["uuid"] for r in episodes if r.get("uuid") and r["uuid"] != episode_uuid]
    if ep_uuids:
        asyncio.create_task(
            reinforce_co_activations(
                graph=episode_store._graph,
                trigger_uuid=episode_uuid,
                result_uuids=ep_uuids,
                learning_rate=get_hebbian_learning_rate(),
                max_pairs=get_hebbian_max_pairs(),
                activation_cap=get_hebbian_activation_cap(),
            )
        )

    kn_uuids = [r["uuid"] for r in knowledge if r.get("uuid")]
    if kn_uuids:
        asyncio.create_task(
            reinforce_knowledge_activations(
                graph=episode_store._graph,
                result_uuids=kn_uuids,
                activation_cap=get_hebbian_activation_cap(),
            )
        )


# ── Background ───────────────────────────────────────────────────────


async def _cold_start_prefill(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    embedding: List[float],
    episode_uuid: str,
    ontology_store=None,
    ontology_top_k: int = 5,
    pipeline: PipelineConfig = None,
) -> None:
    """Background cold-start pre-fill: search FalkorDB and hydrate DragonflyDB session."""
    if pipeline is None:
        pipeline = load_pipeline_config()
    try:
        episodes, knowledge = await _search_falkordb(
            episode_store,
            knowledge_store,
            content,
            embedding,
            episode_uuid,
        )
        await _hydrate_episodes(episode_store, dragonfly, session_id, episodes, episode_uuid)
        await _hydrate_knowledge(episode_store, dragonfly, session_id, knowledge)
        await _search_and_hydrate_ontology(
            ontology_store,
            episode_store,
            dragonfly,
            session_id,
            embedding,
            ontology_top_k,
            pipeline,
            log_prefix="Cold start ontology hydration",
        )
        logger.info(f"Cold start pre-fill done for session {session_id[:8]}")
    except Exception as e:
        logger.warning(f"Cold start pre-fill failed: {e}")


# Semaphore capping total concurrent background_hydrate tasks.
# LLM extraction + embed_batch calls pile up when many observe calls fire in
# rapid succession and overwhelm the embedding API with concurrent requests.
# At most 2 full hydrations run at once; extra calls do only the FalkorDB
# episode store (which is fast) and skip extraction + DragonflyDB hydration.
_HYDRATE_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_hydrate_semaphore() -> asyncio.Semaphore:
    global _HYDRATE_SEMAPHORE
    if _HYDRATE_SEMAPHORE is None:
        _HYDRATE_SEMAPHORE = asyncio.Semaphore(1)
    return _HYDRATE_SEMAPHORE


def _try_acquire_hydrate_slot() -> bool:
    """Non-blocking semaphore acquire. Returns True if slot was obtained.

    Safe because asyncio is single-threaded — no yield point between check and
    decrement so no other coroutine can run between them.
    """
    sem = _get_hydrate_semaphore()
    if sem._value > 0:
        sem._value -= 1
        return True
    return False


def _release_hydrate_slot() -> None:
    _get_hydrate_semaphore()._value += 1


async def background_hydrate(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    embedding: List[float],
    metadata: dict,
    episode_uuid: str,
    prefill_episodes: List[Dict[str, Any]] = None,
    prefill_knowledge: List[Dict[str, Any]] = None,
    ontology_store=None,
    ontology_top_k: int = 5,
    pipeline: PipelineConfig = None,
):
    """Background: store in FalkorDB, extract knowledge, hydrate (warm), Hebbian reinforce, judge.

    Step 1 (FalkorDB store) always runs — ensures episode is persisted.
    Steps 1b-4 (extraction, hydration, Hebbian, judge) run only when a
    concurrency slot is available.  Extra calls are gracefully skipped so rapid
    fire observe sequences don't flood the embedding/LLM APIs.
    """
    if pipeline is None:
        pipeline = load_pipeline_config()
    try:
        # 1. Store in FalkorDB — always run regardless of concurrency pressure
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

        # Steps 1b-4: gate behind a concurrency semaphore.
        # Non-blocking: if at capacity, only log and skip the expensive work.
        _hydrate_slot = _try_acquire_hydrate_slot()
        if not _hydrate_slot:
            logger.debug(
                f"background_hydrate: skipping extraction/hydration for {episode_uuid[:8]} "
                f"(concurrency limit reached)"
            )
            return

        episodes: List[Dict[str, Any]] = []
        knowledge: List[Dict[str, Any]] = []
        try:
            # 1b. Extract and store knowledge from this observation
            if pipeline.extract_knowledge:
                try:
                    from ..intelligence.extract.knowledge import (
                        extract_knowledge as _extract_knowledge,
                    )

                    mission_data = {
                        "task": metadata.get("source", "observe"),
                        "status": "completed",
                        "output": content,
                        "context": content,
                        "data_source_type": "conversation",
                        "iterations": 1,
                        "state": {
                            "state_description": content[:2000],
                            "outputs": [{"iteration": 1, "output": content[:4000]}],
                        },
                    }
                    knowledge_entries = await _extract_knowledge(
                        mission_data=mission_data,
                        reflection="",
                        data_source_type="conversation",
                    )
                    if knowledge_entries:
                        await knowledge_store.store_knowledge(
                            entries=knowledge_entries,
                            source_mission=metadata.get("source", "observe"),
                            mission_status="completed",
                            source_episode_uuid=episode_uuid,
                        )
                        logger.info(
                            f"Knowledge extracted: {len(knowledge_entries)} entries "
                            f"from observe {episode_uuid[:8]}"
                        )
                        # Mark episode so CurationWorker skips re-extraction
                        try:
                            await episode_store._graph.query(
                                "MATCH (e:Episode {uuid: $uuid}) SET e.knowledge_extracted = true",
                                params={"uuid": episode_uuid},
                            )
                        except Exception as fe:
                            logger.warning(f"Failed to set knowledge_extracted flag: {fe}")
                except Exception as e:
                    logger.warning(f"Knowledge extraction in observe failed: {e}")

            # 2. Get episodes + knowledge (cold: reuse pre-fill, warm: search + hydrate)
            if prefill_episodes is not None:
                episodes = prefill_episodes
                knowledge = prefill_knowledge or []
            else:
                episodes, knowledge = await _search_falkordb(
                    episode_store,
                    knowledge_store,
                    content,
                    embedding,
                    episode_uuid,
                )
                ep_count = await _hydrate_episodes(
                    episode_store,
                    dragonfly,
                    session_id,
                    episodes,
                    episode_uuid,
                )
                kn_count = await _hydrate_knowledge(
                    episode_store,
                    dragonfly,
                    session_id,
                    knowledge,
                )
                onto_count = await _search_and_hydrate_ontology(
                    ontology_store,
                    episode_store,
                    dragonfly,
                    session_id,
                    embedding,
                    ontology_top_k,
                    pipeline,
                    log_prefix="Background ontology hydration",
                )
                logger.info(
                    f"Hydration done: {ep_count + kn_count + onto_count} entries added to "
                    f"session {session_id[:8]} (ep={ep_count}, kn={kn_count}, onto={onto_count})"
                )

            # 3. Hebbian reinforcement
            if pipeline.hebbian_reinforcement:
                await _reinforce_hebbian(episode_store, episode_uuid, episodes, knowledge)

            # 4. Judge
            if pipeline.judge_observation:
                try:
                    judge_result = await judge_observation(
                        content=content,
                        source=metadata.get("source", ""),
                    )
                    logger.info(
                        f"Judge: uuid={episode_uuid[:8]}, "
                        f"type={judge_result['observation_type']}, "
                        f"importance={judge_result['importance']}"
                    )
                except Exception as e:
                    logger.warning(f"Background judge failed: {e}")

        finally:
            _release_hydrate_slot()

    except Exception as e:
        logger.error(f"Background hydration error: {e}", exc_info=True)


# ── Main entry point ─────────────────────────────────────────────────


async def observe_core(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    timestamp: str = None,
    source: str = None,
    metadata: dict = None,
    read_only: bool = False,
    summarize: bool = False,
    top_k: int = 10,
    knowledge_top_k: int = 10,
    minimal: bool = False,
    ontology_store=None,
    ontology_top_k: int = 5,
    causal_store=None,
    parent_session_id: str = None,
) -> dict:
    """Core observe logic — store, summarize, return context.

    Cold start: reinterpret → FalkorDB search → pre-fill DragonflyDB.
    Warm: DragonflyDB already populated by background hydration.
    Both paths converge: add to DragonflyDB → LLM summarize session → return.

    If read_only=True, skip all writes and use the warm path summarization only.
    If minimal=True, skip DragonflyDB entirely — return only FalkorDB knowledge
      (knowledge_top_k entries) + the most semantically relevant raw episode.
      Implies read_only.

    If parent_session_id is provided, the session is linked to its parent in
    FalkorDB and ancestor context is included in all FalkorDB searches
    (inherited scope: current session + all ancestors).
    """
    # Scope
    episode_store._group_id = session_id
    knowledge_store._group_id = session_id

    # Resolve inherited scope (current session + all ancestors).
    # Always reset _scope_group_ids on exit so subsequent requests from other
    # sessions (e.g. direct /knowledge/search calls) are not polluted.
    ancestor_ids = await episode_store.get_ancestor_session_ids(session_id)
    scope_ids = [session_id] + ancestor_ids
    episode_store._scope_group_ids = scope_ids if len(scope_ids) > 1 else None
    knowledge_store._scope_group_ids = scope_ids if len(scope_ids) > 1 else None

    try:
        return await _observe_core_inner(
            episode_store=episode_store,
            knowledge_store=knowledge_store,
            dragonfly=dragonfly,
            session_id=session_id,
            content=content,
            timestamp=timestamp,
            source=source,
            metadata=metadata,
            read_only=read_only,
            summarize=summarize,
            top_k=top_k,
            knowledge_top_k=knowledge_top_k,
            minimal=minimal,
            ontology_store=ontology_store,
            ontology_top_k=ontology_top_k,
            causal_store=causal_store,
            parent_session_id=parent_session_id,
        )
    finally:
        episode_store._scope_group_ids = None
        knowledge_store._scope_group_ids = None


async def _observe_core_inner(
    episode_store,
    knowledge_store,
    dragonfly,
    session_id: str,
    content: str,
    timestamp: str = None,
    source: str = None,
    metadata: dict = None,
    read_only: bool = False,
    summarize: bool = False,
    top_k: int = 10,
    knowledge_top_k: int = 10,
    minimal: bool = False,
    ontology_store=None,
    ontology_top_k: int = 5,
    causal_store=None,
    parent_session_id: str = None,
) -> dict:

    # Persist session node + parent link (fire-and-forget, idempotent MERGE)
    if not read_only:
        asyncio.create_task(episode_store.ensure_session(session_id, parent_session_id))

    if minimal:
        # Fast path: knowledge + ontology nodes + 1 most relevant episode, no DragonflyDB
        try:
            embedding = await episode_store._embed(content)
        except Exception as e:
            logger.warning(f"Embedding failed in minimal observe: {e}")
            embedding = None

        search_coros = [
            knowledge_store.search_hybrid(
                query=content,
                top_k=knowledge_top_k,
                min_score=_knowledge_params()["min_score"],
            ),
            episode_store.search_episodes(
                query=content,
                top_k=1,
                episode_type="raw",
                min_score=0.0,
            ),
        ]
        # Add ontology search if store is available and embedding succeeded
        if ontology_store is not None and embedding is not None:
            search_coros.append(
                ontology_store.search_nodes(
                    embedding=embedding,
                    top_k=ontology_top_k,
                    group_id=session_id,
                    min_score=get_retrieval_ontology_min_score(),
                )
            )
            include_ontology = True
        else:
            include_ontology = False

        if include_ontology:
            knowledge_results, relevant_episodes, ontology_results = await asyncio.gather(
                *search_coros
            )
        else:
            knowledge_results, relevant_episodes = await asyncio.gather(*search_coros)
            ontology_results = []

        entries: Dict[str, Any] = {}
        for kn in knowledge_results:
            kn_uuid = kn.get("uuid", "")
            entries[f"kn_{kn_uuid}"] = {
                "content": kn.get("content", ""),
                "source_type": "hydrated_knowledge",
                "created_at": 0,
                "rank": kn.get("score", 0.75),
            }
        for node in ontology_results or []:
            node_uuid = node.get("uuid", "")
            summary = node.get("summary", "")
            if node_uuid and summary:
                display = node.get("display_name") or node.get("name", "")
                entries[f"onto_{node_uuid}"] = {
                    "content": f"{display}: {summary}" if display else summary,
                    "source_type": "ontology_node",
                    "created_at": 0,
                    "rank": node.get("score", 0.85),
                }
        for ep in relevant_episodes:
            ep_uuid = ep.get("uuid", "")
            entries[f"ep_{ep_uuid}"] = {
                "content": ep.get("content", ""),
                "source_type": "relevant_episode",
                "created_at": ep.get("created_at", 0),
                "rank": ep.get("score", 0.0),
            }
        from ..intelligence.synthesis.summarize_context import _format_entries

        context = _format_entries(entries) if entries else ""
        logger.info(
            f"minimal observe: {len(knowledge_results)} knowledge + "
            f"{len(ontology_results or [])} ontology nodes + "
            f"{len(relevant_episodes)} relevant episode → {len(context)} chars"
        )
        return {
            "episode_uuid": "",
            "observation_type": "observe",
            "context": context,
            "is_cold": False,
            "search_labels": [],
            "search_query": content,
            "session_id": session_id,
            "parent_session_id": parent_session_id,
        }

    metadata = dict(metadata or {})
    if timestamp:
        metadata["date_time"] = timestamp
    if source:
        metadata["source"] = source

    # Load pipeline feature flags once for this call
    pipeline = load_pipeline_config()

    from ..intelligence.timing import SpanTracer

    tracer = SpanTracer(dragonfly, "observe", session_id)

    episode_uuid = ""
    search_labels = []
    search_query = content
    is_cold = False
    falkor_episodes = None
    falkor_knowledge = None
    embedding = None

    if not read_only:
        # Step 1: Embed + store in DragonflyDB
        _sid, _t0 = tracer.start("embed")
        try:
            embedding = await episode_store._embed(content)
            tracer.end(_sid, "embed", _t0)
        except Exception as e:
            tracer.end(_sid, "embed", _t0, error=True)
            logger.warning(f"Embedding failed, returning empty context: {e}")
            return {
                "episode_uuid": str(uuid4()),
                "observation_type": "observe",
                "context": "",
                "is_cold": False,
                "search_labels": [],
                "search_query": "",
                "session_id": session_id,
                "parent_session_id": parent_session_id,
            }
        episode_uuid = str(uuid4())

        # Step 2: Cold start pre-fill — read count BEFORE session_add so count==0
        # means this is truly the first observation in this session.
        session_entry_count = await dragonfly.session_count(session_id)
        is_cold = session_entry_count == 0

        _sid, _t0 = tracer.start("session_add")
        await dragonfly.session_add(
            session_id=session_id,
            entry_uuid=episode_uuid,
            content=content,
            embedding=embedding,
            metadata=metadata,
            source_type="local",
        )
        tracer.end(_sid, "session_add", _t0)

        if is_cold:
            logger.info(f"Cold start for session {session_id[:8]}")
            await _cold_start_prefill(
                episode_store=episode_store,
                knowledge_store=knowledge_store,
                dragonfly=dragonfly,
                session_id=session_id,
                content=content,
                embedding=embedding,
                episode_uuid=episode_uuid,
                ontology_store=ontology_store,
                ontology_top_k=ontology_top_k,
                pipeline=pipeline,
            )

    # Step 3: Get session entries — use 3D scoring (semantic + temporal + Hebbian)
    # instead of recency cap so the most relevant entries survive, not the most recent.
    # read_only: embed here (cheap; LLM summarization is already skipped by default).
    if read_only and embedding is None:
        try:
            embedding = await episode_store._embed(content)
        except Exception as e:
            logger.warning(f"Embedding failed in read_only: {e}")
            embedding = None

    if embedding is not None:
        # Semantic search within session → top 100 by cosine similarity
        _sid, _t0 = tracer.start("session_search")
        search_results = await dragonfly.session_search(
            session_id=session_id,
            query_embedding=embedding,
            top_k=top_k,
            min_score=0.0,
        )
        tracer.end(_sid, "session_search", _t0)
        if episode_uuid:
            search_results = [r for r in search_results if r.get("uuid") != episode_uuid]

        # Apply 3D scoring: semantic + temporal + Hebbian
        _sid, _t0 = tracer.start("score_3dim")
        search_results = await _score_3dim(
            episode_store,
            search_results,
            episode_uuid,
            alpha=get_episode_alpha(),
            half_life=get_episode_half_life(),
        )
        tracer.end(_sid, "score_3dim", _t0)
        # Propagate 3D composite score as rank for context ordering
        for r in search_results:
            r["rank"] = r.get("score", 0.0)
        entries = {r["uuid"]: r for r in search_results}

        # Standard warm path: augment with OntologyNode summaries from FalkorDB.
        # These are not in DragonflyDB unless hydrated at cold start, so search fresh.
        if not read_only and ontology_store is not None:
            try:
                onto_results = await ontology_store.search_nodes(
                    embedding=embedding,
                    top_k=ontology_top_k,
                    group_id=session_id,
                    min_score=get_retrieval_ontology_min_score(),
                )
                for node in onto_results:
                    node_uuid = node.get("uuid", "")
                    summary = node.get("summary", "")
                    if node_uuid and summary:
                        key = f"onto_{node_uuid}"
                        if key not in entries:
                            display = node.get("display_name") or node.get("name", "")
                            entries[key] = {
                                "content": f"{display}: {summary}" if display else summary,
                                "source_type": "ontology_node",
                                "created_at": 0,
                                "rank": node.get("score", 0.85),
                            }
            except Exception as e:
                logger.warning(f"OntologyNode warm-path search failed: {e}")

        # Augment with causal beliefs from CausalClaimStore
        if causal_store is not None:
            try:
                causal_results = await causal_store.search_claims(
                    embedding=embedding,
                    top_k=3,
                    group_id=session_id,
                    min_score=0.4,
                )
                for claim in causal_results:
                    claim_uuid = claim.get("uuid", "")
                    if claim_uuid:
                        key = f"causal_{claim_uuid}"
                        if key not in entries:
                            conf = claim.get("confidence", 0.0)
                            mech = claim.get("mechanism", "")
                            content_str = (
                                f"[Causal, confidence={conf:.2f}] "
                                f"{claim.get('cause_summary', '')} → {claim.get('effect_summary', '')}"
                            )
                            if mech:
                                content_str += f" ({mech})"
                            entries[key] = {
                                "content": content_str,
                                "source_type": "causal_claim",
                                "created_at": 0,
                                "rank": claim.get("score", 0.80),
                            }
            except Exception as e:
                logger.warning(f"CausalClaim warm-path search failed: {e}")
    else:
        # Fallback: recency cap (no embedding available)
        entries = await dragonfly.session_get_all(session_id)
        if episode_uuid:
            entries.pop(episode_uuid, None)
        if len(entries) > top_k:
            sorted_items = sorted(
                entries.items(), key=lambda x: x[1].get("created_at", 0), reverse=True
            )
            entries = dict(sorted_items[:top_k])

    # read_only: augment with a fresh synchronous search from FalkorDB covering
    # episodes, knowledge, and ontology nodes. Episodes are the most critical —
    # without them the session (which is empty for benchmarks not using observe-mode
    # ingest) has no raw conversation evidence to answer factual questions.
    if read_only and embedding is not None:
        onto_coro = (
            ontology_store.search_nodes(
                embedding=embedding,
                top_k=ontology_top_k,
                group_id=session_id,
                min_score=get_retrieval_ontology_min_score(),
            )
            if ontology_store is not None
            else asyncio.sleep(0)
        )
        try:
            _kp = _knowledge_params()
            _rp = _retrieval_params()
            kn_results, ep_results, onto_results = await asyncio.gather(
                knowledge_store.search_hybrid(
                    query=content,
                    top_k=knowledge_top_k,
                    min_score=_kp["min_score"],
                ),
                episode_store._search_with_embedding(
                    embedding=embedding,
                    top_k=_rp["top_k"],
                    min_score=_rp["min_score"],
                    expand_adjacent=True,
                    expansion_hops=1,
                    include_embedding=False,
                ),
                onto_coro,
                return_exceptions=True,
            )
            if isinstance(kn_results, Exception):
                kn_results = []
            if isinstance(ep_results, Exception):
                ep_results = []
            if isinstance(onto_results, Exception) or not isinstance(onto_results, list):
                onto_results = []

            for ep in ep_results:
                ep_uuid = ep.get("uuid", "")
                if ep_uuid and f"ep_{ep_uuid}" not in entries and ep_uuid not in entries:
                    entries[f"ep_{ep_uuid}"] = {
                        "content": ep.get("content", ""),
                        "source_type": "hydrated",
                        "created_at": ep.get("created_at", 0),
                        "rank": ep.get("score", 0.0),
                    }
            for kn in kn_results:
                kn_uuid = kn.get("uuid", "")
                key = f"kn_{kn_uuid}"
                if kn_uuid and key not in entries:
                    entries[key] = {
                        "content": kn.get("content", ""),
                        "source_type": "hydrated_knowledge",
                        "created_at": 0,
                        "rank": kn.get("score", 0.75),
                    }
            for node in onto_results:
                node_uuid = node.get("uuid", "")
                summary = node.get("summary", "")
                if node_uuid and summary:
                    key = f"onto_{node_uuid}"
                    if key not in entries:
                        display = node.get("display_name") or node.get("name", "")
                        entries[key] = {
                            "content": f"{display}: {summary}" if display else summary,
                            "source_type": "ontology_node",
                            "created_at": 0,
                            "rank": node.get("score", 0.85),
                        }
            logger.info(
                f"read_only augment: {len(ep_results)} episodes + "
                f"{len(kn_results)} knowledge + {len(onto_results)} ontology nodes"
            )
        except Exception as e:
            logger.warning(f"read_only search failed: {e}")

    context = ""
    if entries:
        _sid, _t0 = tracer.start("format")
        if summarize:
            from ..intelligence.synthesis.summarize_context import summarize_context

            context = await summarize_context(
                current_observation=content,
                session_entries=entries,
            )
        else:
            from ..intelligence.synthesis.summarize_context import _format_entries

            context = _format_entries(entries)
        tracer.end(_sid, "format", _t0)

    if not read_only:
        # Step 4: Fire background
        asyncio.create_task(
            background_hydrate(
                episode_store,
                knowledge_store,
                dragonfly,
                session_id,
                content,
                embedding,
                metadata,
                episode_uuid,
                prefill_episodes=falkor_episodes if is_cold else None,
                prefill_knowledge=falkor_knowledge if is_cold else None,
                ontology_store=ontology_store,
                ontology_top_k=ontology_top_k,
                pipeline=pipeline,
            )
        )

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
        "session_id": session_id,
        "parent_session_id": parent_session_id,
    }
