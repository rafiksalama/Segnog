"""Pipelines router — composite operations that reduce round trips."""

from fastapi import APIRouter, Request

from ..dependencies import (
    get_dragonfly,
    get_short_term,
    get_episode_store,
    get_knowledge_store,
    get_artifact_store,
)
from ...grpc.service_handler import MemoryServiceHandler

router = APIRouter()


def _build_handler(request: Request) -> MemoryServiceHandler:
    """Build a MemoryServiceHandler from request's app state."""
    return MemoryServiceHandler(
        dragonfly=get_dragonfly(request),
        short_term=get_short_term(request),
        episode_store=get_episode_store(request),
        knowledge_store=get_knowledge_store(request),
        artifact_store=get_artifact_store(request),
    )


@router.post("/pipelines/startup")
async def startup_pipeline(body: dict, request: Request):
    """
    Full startup pipeline — replaces 7-step startup sequence.

    Runs: reinterpret → search episodes → search knowledge/artifacts (parallel)
    → filter → tool stats → infer state → synthesize background
    """
    handler = _build_handler(request)
    return await handler.startup_pipeline({
        "scope": {
            "group_id": body.get("group_id", "default"),
            "workflow_id": body.get("workflow_id", "default"),
        },
        "task": body.get("task", ""),
        "model": body.get("model"),
    })


@router.post("/pipelines/curation")
async def run_curation(body: dict, request: Request):
    """
    Full curation pipeline — replaces CuratorWorkflow.

    Runs: reflect → store reflection → extract knowledge → store knowledge
    → extract artifacts → store artifacts → compress events
    """
    handler = _build_handler(request)
    return await handler.run_curation({
        "scope": {
            "group_id": body.get("group_id", "default"),
            "workflow_id": body.get("workflow_id", "default"),
        },
        "mission_data_json": body.get("mission_data_json", "{}"),
        "model": body.get("model"),
    })
