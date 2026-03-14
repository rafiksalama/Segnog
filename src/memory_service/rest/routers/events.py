"""Events router — log and retrieve events from DragonflyDB streams."""

from fastapi import APIRouter, Request

from ...dto.events import (
    LogEventRequest,
    LogEventResponse,
    EventRecord,
    GetRecentEventsResponse,
    SearchEventsResponse,
)
from ..dependencies import get_dragonfly

router = APIRouter()


@router.post("/events", response_model=LogEventResponse)
async def log_event(body: LogEventRequest, request: Request):
    dragonfly = get_dragonfly(request)
    dragonfly.set_scope(group_id=body.group_id, workflow_id=body.workflow_id)
    event_id = await dragonfly.log_event(body.event_type, body.event_data)
    return LogEventResponse(event_id=event_id or "")


@router.get("/events/recent", response_model=GetRecentEventsResponse)
async def get_recent_events(
    request: Request,
    group_id: str = "default",
    workflow_id: str = "default",
    count: int = 10,
    event_type: str = None,
):
    dragonfly = get_dragonfly(request)
    dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
    raw_events = await dragonfly.get_recent_events(count=count, event_type=event_type)
    events = [
        EventRecord(
            event_id=e.get("event_id", ""),
            stream_id=e.get("stream_id", ""),
            event_type=e.get("type", ""),
            timestamp=e.get("timestamp", 0.0),
            group_id=e.get("group_id", ""),
            workflow_id=e.get("workflow_id", ""),
            data=e.get("data", {}),
        )
        for e in raw_events
    ]
    return GetRecentEventsResponse(events=events)


@router.post("/events/search", response_model=SearchEventsResponse)
async def search_events(
    body: dict,
    request: Request,
):
    """Search events — currently returns recent events filtered by type."""
    dragonfly = get_dragonfly(request)
    group_id = body.get("group_id", "default")
    workflow_id = body.get("workflow_id", "default")
    dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)

    event_types = body.get("event_types", [])
    limit = body.get("limit", 50)

    # Get all recent and filter by types
    raw_events = await dragonfly.get_recent_events(count=limit)
    if event_types:
        raw_events = [e for e in raw_events if e.get("type") in event_types]

    events = [
        EventRecord(
            event_id=e.get("event_id", ""),
            stream_id=e.get("stream_id", ""),
            event_type=e.get("type", ""),
            timestamp=e.get("timestamp", 0.0),
            group_id=e.get("group_id", ""),
            workflow_id=e.get("workflow_id", ""),
            data=e.get("data", {}),
        )
        for e in raw_events
    ]
    return SearchEventsResponse(events=events)
