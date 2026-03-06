"""Artifact DTOs for REST + internal use."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArtifactEntry(BaseModel):
    name: str
    artifact_type: str = "file"
    path: str = ""
    description: str = ""
    labels: List[str] = Field(default_factory=list)


class StoreArtifactsRequest(BaseModel):
    group_id: str = "default"
    entries: List[ArtifactEntry]
    source_mission: str
    mission_status: str = "success"
    source_episode_uuid: str = ""


class StoreArtifactsResponse(BaseModel):
    uuids: List[str]


class ArtifactRecord(BaseModel):
    uuid: str = ""
    name: str = ""
    artifact_type: str = ""
    path: str = ""
    description: str = ""
    labels: List[str] = Field(default_factory=list)
    source_mission: str = ""
    mission_status: str = ""
    created_at: float = 0.0
    score: float = 0.0


class SearchArtifactsRequest(BaseModel):
    group_id: str = "default"
    query: str
    labels: List[str] = Field(default_factory=list)
    top_k: int = 10
    min_score: float = 0.45


class SearchArtifactsResponse(BaseModel):
    entries: List[ArtifactRecord]
