"""Event DTOs for REST + internal use."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LogEventRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    event_type: str = Field(..., min_length=1)
    event_data: Dict[str, Any]
    context: Optional[str] = None


class LogEventResponse(BaseModel):
    event_id: str


class EventRecord(BaseModel):
    event_id: str = ""
    stream_id: str = ""
    event_type: str = ""
    timestamp: float = 0.0
    group_id: str = ""
    workflow_id: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


class GetRecentEventsRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    count: int = Field(10, ge=1, le=1000)
    event_type_filter: Optional[str] = None


class GetRecentEventsResponse(BaseModel):
    events: List[EventRecord]


class SearchEventsRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    query: str = Field(..., min_length=1)
    event_types: List[str] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=1000)


class SearchEventsResponse(BaseModel):
    events: List[EventRecord]
