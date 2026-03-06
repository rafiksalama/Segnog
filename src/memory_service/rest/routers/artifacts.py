"""Artifacts router — CRUD + search for artifacts in FalkorDB."""

import json
from fastapi import APIRouter, Request, HTTPException

from ...dto.artifacts import (
    StoreArtifactsRequest,
    StoreArtifactsResponse,
    ArtifactRecord,
    SearchArtifactsRequest,
    SearchArtifactsResponse,
)
from ..dependencies import get_artifact_store

router = APIRouter()


@router.post("/artifacts", response_model=StoreArtifactsResponse)
async def store_artifacts(body: StoreArtifactsRequest, request: Request):
    store = get_artifact_store(request)
    store._group_id = body.group_id
    entries = [e.model_dump() for e in body.entries]
    uuids = await store.store_artifacts(
        entries=entries,
        source_mission=body.source_mission,
        mission_status=body.mission_status,
        source_episode_uuid=body.source_episode_uuid,
    )
    return StoreArtifactsResponse(uuids=uuids)


@router.post("/artifacts/search", response_model=SearchArtifactsResponse)
async def search_artifacts(body: SearchArtifactsRequest, request: Request):
    store = get_artifact_store(request)
    store._group_id = body.group_id
    raw = await store.search_hybrid(
        query=body.query,
        labels=body.labels or None,
        top_k=body.top_k,
        min_score=body.min_score,
    )
    entries = [_to_record(r) for r in raw]
    return SearchArtifactsResponse(entries=entries)


@router.get("/artifacts/{uuid}")
async def get_artifact(uuid: str, request: Request, group_id: str = "default"):
    store = get_artifact_store(request)
    store._group_id = group_id
    result = await store.get_by_uuid(uuid)
    if not result:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact": _to_record(result).model_dump(), "found": True}


@router.get("/artifacts/recent/list")
async def list_recent(
    request: Request,
    group_id: str = "default",
    limit: int = 50,
):
    store = get_artifact_store(request)
    store._group_id = group_id
    raw = await store.list_recent(limit=limit)
    entries = [_to_record(r) for r in raw]
    return {"entries": [e.model_dump() for e in entries]}


@router.delete("/artifacts/{uuid}")
async def delete_artifact(uuid: str, request: Request, group_id: str = "default"):
    store = get_artifact_store(request)
    store._group_id = group_id
    existed = await store.delete_by_uuid(uuid)
    return {"existed": existed}


def _to_record(r: dict) -> ArtifactRecord:
    labels = r.get("labels", [])
    if isinstance(labels, str):
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    return ArtifactRecord(
        uuid=r.get("uuid", ""),
        name=r.get("name", ""),
        artifact_type=r.get("artifact_type", ""),
        path=r.get("path", ""),
        description=r.get("description", ""),
        labels=labels,
        source_mission=r.get("source_mission", ""),
        mission_status=r.get("mission_status", ""),
        created_at=r.get("created_at", 0.0),
        score=r.get("score", 0.0),
    )
