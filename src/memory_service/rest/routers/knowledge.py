"""Knowledge router — store and search knowledge in FalkorDB."""

from fastapi import APIRouter, Request

from ...dto.knowledge import (
    StoreKnowledgeRequest,
    StoreKnowledgeResponse,
    KnowledgeRecord,
    SearchKnowledgeRequest,
    SearchKnowledgeResponse,
    SearchByLabelsRequest,
)
from ..dependencies import get_knowledge_store

router = APIRouter()


@router.post("/knowledge", response_model=StoreKnowledgeResponse)
async def store_knowledge(body: StoreKnowledgeRequest, request: Request):
    store = get_knowledge_store(request)
    store._group_id = body.group_id
    entries = [e.model_dump() for e in body.entries]
    uuids = await store.store_knowledge(
        entries=entries,
        source_mission=body.source_mission,
        mission_status=body.mission_status,
        source_episode_uuid=body.source_episode_uuid,
    )
    return StoreKnowledgeResponse(uuids=uuids)


@router.post("/knowledge/search", response_model=SearchKnowledgeResponse)
async def search_knowledge(body: SearchKnowledgeRequest, request: Request):
    store = get_knowledge_store(request)
    store._group_id = body.group_id
    raw = await store.search_hybrid(
        query=body.query,
        labels=body.labels or None,
        top_k=body.top_k,
        min_score=body.min_score,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    entries = [_to_record(r) for r in raw]
    return SearchKnowledgeResponse(entries=entries)


@router.post("/knowledge/search-labels", response_model=SearchKnowledgeResponse)
async def search_by_labels(body: SearchByLabelsRequest, request: Request):
    store = get_knowledge_store(request)
    store._group_id = body.group_id
    raw = await store.search_by_labels(
        labels=body.labels,
        top_k=body.top_k,
    )
    entries = [_to_record(r) for r in raw]
    return SearchKnowledgeResponse(entries=entries)


def _to_record(r: dict) -> KnowledgeRecord:
    labels = r.get("labels", [])
    if isinstance(labels, str):
        import json
        try:
            labels = json.loads(labels)
        except Exception:
            labels = []
    return KnowledgeRecord(
        uuid=r.get("uuid", ""),
        content=r.get("content", ""),
        knowledge_type=r.get("knowledge_type", ""),
        labels=labels,
        confidence=r.get("confidence", 0.0),
        source_mission=r.get("source_mission", ""),
        created_at=r.get("created_at", 0.0),
        event_date=r.get("event_date", ""),
        score=r.get("score", 0.0),
    )
