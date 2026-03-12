"""Observe router — thin wrapper around core observe logic."""

from fastapi import APIRouter, Request

from ...dto.episodes import ObserveRequest, ObserveResponse
from ...core.observe import observe_core
from ..dependencies import (
    get_dragonfly, get_episode_store, get_knowledge_store,
)

router = APIRouter()


@router.post("/observe", response_model=ObserveResponse)
async def observe(body: ObserveRequest, request: Request):
    """
    Observe endpoint — short-term first architecture.

    Hot path: embed -> store in DragonflyDB -> LLM summarize session -> return context.
    Background: store in FalkorDB -> search -> hydrate session -> judge.
    Cold start: synchronous FalkorDB search to pre-fill session.
    """
    result = await observe_core(
        episode_store=get_episode_store(request),
        knowledge_store=get_knowledge_store(request),
        dragonfly=get_dragonfly(request),
        session_id=body.session_id,
        content=body.content,
        timestamp=body.timestamp,
        source=body.source,
        metadata=dict(body.metadata or {}),
        read_only=body.read_only,
        summarize=body.summarize,
        top_k=body.top_k,
        knowledge_top_k=body.knowledge_top_k,
        minimal=body.minimal,
    )

    return ObserveResponse(
        episode_uuid=result["episode_uuid"],
        observation_type=result["observation_type"],
        context=result["context"],
        search_labels=result.get("search_labels", []),
        search_query=result.get("search_query", ""),
    )
