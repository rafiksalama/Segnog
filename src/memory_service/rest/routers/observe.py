"""Observe router — single-endpoint memory interface."""

import asyncio
import logging

from fastapi import APIRouter, Request

from ...dto.episodes import (
    ObserveRequest, ObserveResponse, ObserveContext, EpisodeRecord,
)
from ...smart.judge_observation import judge_observation
from ..dependencies import get_dragonfly, get_episode_store, get_knowledge_store

logger = logging.getLogger(__name__)

router = APIRouter()

# Importance → retrieval parameters
_IMPORTANCE_PARAMS = {
    "low":    {"top_k": 5,  "min_score": 0.60},
    "medium": {"top_k": 10, "min_score": 0.55},
    "high":   {"top_k": 15, "min_score": 0.50},
}


@router.post("/observe", response_model=ObserveResponse)
async def observe(body: ObserveRequest, request: Request):
    """
    Observe endpoint — accept an observation, judge it, store it,
    and return relevant context automatically.
    """
    episode_store = get_episode_store(request)
    knowledge_store = get_knowledge_store(request)
    dragonfly = get_dragonfly(request)

    # Map session_id to internal scope
    episode_store._group_id = body.session_id
    knowledge_store._group_id = body.session_id
    dragonfly.set_scope(group_id=body.session_id, workflow_id=body.session_id)

    # Inject timestamp into metadata if provided
    metadata = dict(body.metadata or {})
    if body.timestamp:
        metadata["date_time"] = body.timestamp
    if body.source:
        metadata["source"] = body.source

    # ── Step 1: Judge the observation ────────────────────────────────
    judge_result = await judge_observation(
        content=body.content,
        source=body.source or "",
    )

    obs_type = judge_result["observation_type"]
    tier = judge_result["storage_tier"]
    search_query = judge_result["search_query"]
    search_labels = judge_result["search_labels"]
    importance = judge_result["importance"]

    retrieval_params = _IMPORTANCE_PARAMS.get(importance, _IMPORTANCE_PARAMS["medium"])

    # ── Step 2: Store based on judge routing ─────────────────────────
    episode_uuid = ""
    embedding = None

    # Short-term: log event to DragonflyDB
    if tier in ("short_term", "both"):
        try:
            await dragonfly.log_event(obs_type, {
                "content": body.content,
                **(body.metadata or {}),
            })
        except Exception as e:
            logger.warning(f"Failed to log short-term event: {e}")

    # Long-term: store episode in FalkorDB (embed once, reuse for search)
    if tier in ("long_term", "both"):
        try:
            embedding = await episode_store._embed(body.content)
            episode_uuid = await episode_store._store_with_embedding(
                content=body.content,
                embedding=embedding,
                metadata=metadata,
                episode_type="raw",
                auto_link=True,
            )
        except Exception as e:
            logger.error(f"Failed to store episode: {e}")

    # ── Step 3: Retrieve relevant context (parallel) ─────────────────
    episode_results = []
    knowledge_results = []

    try:
        # If we have an embedding from storage, reuse it for episode search
        if embedding is not None:
            ep_task = episode_store._search_with_embedding(
                embedding=embedding,
                top_k=retrieval_params["top_k"],
                min_score=retrieval_params["min_score"],
            )
        else:
            # Short-term only: use search_query text (requires fresh embedding)
            ep_task = episode_store.search_episodes(
                query=search_query,
                top_k=retrieval_params["top_k"],
                min_score=retrieval_params["min_score"],
            )

        kn_task = knowledge_store.search_hybrid(
            query=search_query,
            labels=search_labels if search_labels else None,
            top_k=5,
            min_score=0.50,
        )

        episode_results, knowledge_results = await asyncio.gather(
            ep_task, kn_task,
        )
    except Exception as e:
        logger.error(f"Retrieval failed: {e}")

    # Filter out the just-stored episode from results
    if episode_uuid:
        episode_results = [e for e in episode_results if e.get("uuid") != episode_uuid]

    return ObserveResponse(
        episode_uuid=episode_uuid,
        observation_type=obs_type,
        context=ObserveContext(
            episodes=[EpisodeRecord(**e) for e in episode_results],
            knowledge=knowledge_results,
        ),
    )
