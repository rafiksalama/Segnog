"""Knowledge DTOs for REST + internal use."""

from typing import List, Optional
from pydantic import BaseModel, Field


class KnowledgeEntry(BaseModel):
    content: str = Field(..., min_length=1)
    knowledge_type: str = "fact"
    labels: List[str] = Field(default_factory=list)
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    event_date: Optional[str] = None


class StoreKnowledgeRequest(BaseModel):
    group_id: str = "default"
    entries: List[KnowledgeEntry] = Field(..., min_length=1)
    source_mission: str = Field(..., min_length=1)
    mission_status: str = "success"
    source_episode_uuid: str = ""


class StoreKnowledgeResponse(BaseModel):
    uuids: List[str]


class KnowledgeRecord(BaseModel):
    uuid: str = ""
    content: str = ""
    knowledge_type: str = ""
    labels: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    source_mission: str = ""
    created_at: float = 0.0
    event_date: str = ""
    score: float = 0.0


class SearchKnowledgeRequest(BaseModel):
    group_id: Optional[str] = None
    query: str = Field(..., min_length=1)
    labels: List[str] = Field(default_factory=list)
    top_k: int = Field(10, ge=1, le=1000)
    min_score: float = Field(0.50, ge=0.0, le=1.0)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SearchKnowledgeResponse(BaseModel):
    entries: List[KnowledgeRecord]


class SearchByLabelsRequest(BaseModel):
    group_id: str = "default"
    labels: List[str] = Field(..., min_length=1)
    top_k: int = Field(10, ge=1, le=1000)
