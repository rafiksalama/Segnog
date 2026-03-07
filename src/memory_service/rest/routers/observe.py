"""Observe router — thin wrapper around core observe logic."""

from fastapi import APIRouter, Request

from ...dto.episodes import (
    ObserveRequest, ObserveResponse, ObserveContext, EpisodeRecord,
)
from ...core.observe import observe_core
from ..dependencies import get_dragonfly, get_episode_store, get_knowledge_store

router = APIRouter()


@router.post("/observe", response_model=ObserveResponse)
async def observe(body: ObserveRequest, request: Request):
    """
    Observe endpoint — short-term first architecture.

    Hot path: embed -> store in DragonflyDB session -> search session -> return context.
    Background: store in FalkorDB -> search -> hydrate session -> judge.
    Cold start: synchronous FalkorDB search when session is empty.
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
    )

    # Convert core result to REST response DTOs
    if result["is_cold"]:
        context = ObserveContext(
            episodes=[EpisodeRecord(**e) for e in result["context"]["episodes"]],
            knowledge=result["context"]["knowledge"],
        )
    else:
        context = ObserveContext(
            episodes=[
                EpisodeRecord(
                    uuid=r["uuid"],
                    content=r["content"],
                    metadata=r.get("metadata"),
                    created_at=r.get("created_at", 0),
                    score=r.get("score", 0),
                    source=r.get("source_type", ""),
                )
                for r in result["context"]["episodes"]
            ],
        )

    return ObserveResponse(
        episode_uuid=result["episode_uuid"],
        observation_type=result["observation_type"],
        context=context,
    )
