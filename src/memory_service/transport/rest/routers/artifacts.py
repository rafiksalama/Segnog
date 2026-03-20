"""Artifacts router — CRUD + search for artifacts in FalkorDB."""

from fastapi import APIRouter, Request, HTTPException

from ..dto.artifacts import (
    StoreArtifactsRequest,
    StoreArtifactsResponse,
    ArtifactRecord,
    SearchArtifactsRequest,
    SearchArtifactsResponse,
)
from ..dependencies import get_service, parse_json_labels

router = APIRouter()


@router.post("/artifacts", response_model=StoreArtifactsResponse)
async def store_artifacts(body: StoreArtifactsRequest, request: Request):
    svc = get_service(request)
    entries = [e.model_dump() for e in body.entries]
    uuids = await svc.store_artifacts(
        group_id=body.group_id,
        entries=entries,
        source_mission=body.source_mission,
        mission_status=body.mission_status,
        source_episode_uuid=body.source_episode_uuid,
    )
    return StoreArtifactsResponse(uuids=uuids)


@router.post("/artifacts/search", response_model=SearchArtifactsResponse)
async def search_artifacts(body: SearchArtifactsRequest, request: Request):
    svc = get_service(request)
    raw = await svc.search_artifacts(
        group_id=body.group_id,
        query=body.query,
        labels=body.labels or None,
        top_k=body.top_k,
        min_score=body.min_score,
    )
    entries = [_to_record(r) for r in raw]
    return SearchArtifactsResponse(entries=entries)


@router.get("/artifacts/{uuid}")
async def get_artifact(uuid: str, request: Request, group_id: str = "default"):
    svc = get_service(request)
    result = await svc.get_artifact(group_id=group_id, uuid=uuid)
    if not result:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact": _to_record(result).model_dump(), "found": True}


@router.get("/artifacts/recent/list")
async def list_recent(
    request: Request,
    group_id: str = "default",
    limit: int = 50,
):
    svc = get_service(request)
    raw = await svc.list_recent_artifacts(group_id=group_id, limit=limit)
    entries = [_to_record(r) for r in raw]
    return {"entries": [e.model_dump() for e in entries]}


@router.delete("/artifacts/{uuid}")
async def delete_artifact(uuid: str, request: Request, group_id: str = "default"):
    svc = get_service(request)
    existed = await svc.delete_artifact(group_id=group_id, uuid=uuid)
    return {"existed": existed}


def _to_record(r: dict) -> ArtifactRecord:
    return ArtifactRecord(
        uuid=r.get("uuid", ""),
        name=r.get("name", ""),
        artifact_type=r.get("artifact_type", ""),
        path=r.get("path", ""),
        description=r.get("description", ""),
        labels=parse_json_labels(r.get("labels", [])),
        source_mission=r.get("source_mission", ""),
        mission_status=r.get("mission_status", ""),
        created_at=r.get("created_at", 0.0),
        score=r.get("score", 0.0),
    )
