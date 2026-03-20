"""Pipelines router — composite operations that reduce round trips."""

import json

from fastapi import APIRouter, Request

from ..dependencies import get_service

router = APIRouter()


@router.post("/pipelines/startup")
async def startup_pipeline(body: dict, request: Request):
    """
    Full startup pipeline — replaces 7-step startup sequence.

    Runs: reinterpret → search episodes → search knowledge/artifacts (parallel)
    → filter → tool stats → infer state → synthesize background
    """
    svc = get_service(request)
    return await svc.startup_pipeline(
        group_id=body.get("group_id", "default"),
        workflow_id=body.get("workflow_id", "default"),
        task=body.get("task", ""),
        model=body.get("model"),
    )


@router.post("/pipelines/curation")
async def run_curation(body: dict, request: Request):
    """
    Full curation pipeline — replaces CuratorWorkflow.

    Runs: reflect → store reflection → extract knowledge → store knowledge
    → extract artifacts → store artifacts → compress events
    """
    svc = get_service(request)
    mission_data_json = body.get("mission_data_json", "{}")
    if isinstance(mission_data_json, str):
        mission_data = json.loads(mission_data_json)
    else:
        mission_data = mission_data_json

    return await svc.run_curation(
        group_id=body.get("group_id", "default"),
        workflow_id=body.get("workflow_id", "default"),
        mission_data=mission_data,
        source_episode_uuids=body.get("source_episode_uuids", []),
        model=body.get("model"),
    )
