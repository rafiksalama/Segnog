"""Artifact DTOs for REST + internal use."""

from typing import List
from pydantic import BaseModel, Field


class ArtifactEntry(BaseModel):
    name: str = Field(..., min_length=1)
    artifact_type: str = "file"
    path: str = ""
    description: str = ""
    labels: List[str] = Field(default_factory=list)


class StoreArtifactsRequest(BaseModel):
    group_id: str = "default"
    entries: List[ArtifactEntry] = Field(..., min_length=1)
    source_mission: str = Field(..., min_length=1)
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
    query: str = Field(..., min_length=1)
    labels: List[str] = Field(default_factory=list)
    top_k: int = Field(10, ge=1, le=1000)
    min_score: float = Field(0.45, ge=0.0, le=1.0)


class SearchArtifactsResponse(BaseModel):
    entries: List[ArtifactRecord]
