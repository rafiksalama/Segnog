"""Knowledge DTOs for REST + internal use."""

from typing import List, Optional
from pydantic import BaseModel, Field


class KnowledgeEntry(BaseModel):
    content: str
    knowledge_type: str = "fact"
    labels: List[str] = Field(default_factory=list)
    confidence: float = 0.8
    event_date: Optional[str] = None


class StoreKnowledgeRequest(BaseModel):
    group_id: str = "default"
    entries: List[KnowledgeEntry]
    source_mission: str
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
    group_id: str = "default"
    query: str
    labels: List[str] = Field(default_factory=list)
    top_k: int = 10
    min_score: float = 0.50
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SearchKnowledgeResponse(BaseModel):
    entries: List[KnowledgeRecord]


class SearchByLabelsRequest(BaseModel):
    group_id: str = "default"
    labels: List[str]
    top_k: int = 10
