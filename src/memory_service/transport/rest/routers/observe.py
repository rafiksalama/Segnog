"""Observe router — thin wrapper around core observe logic."""

from fastapi import APIRouter, Request

from ..dto.episodes import ObserveRequest, ObserveResponse
from ..dependencies import get_service

router = APIRouter()


@router.post("/observe", response_model=ObserveResponse)
async def observe(body: ObserveRequest, request: Request):
    """
    Observe endpoint — short-term first architecture.

    Hot path: embed -> store in DragonflyDB -> LLM summarize session -> return context.
    Background: store in FalkorDB -> search -> hydrate session -> judge.
    Cold start: synchronous FalkorDB search to pre-fill session.
    """
    svc = get_service(request)
    result = await svc.observe(
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
        parent_session_id=body.parent_session_id,
    )

    return ObserveResponse(
        episode_uuid=result["episode_uuid"],
        observation_type=result["observation_type"],
        context=result["context"],
        context_sources=result.get("context_sources", {}),
        search_labels=result.get("search_labels", []),
        search_query=result.get("search_query", ""),
        session_id=result.get("session_id", body.session_id),
        parent_session_id=result.get("parent_session_id", body.parent_session_id),
    )
