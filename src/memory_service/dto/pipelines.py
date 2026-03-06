"""Pipeline DTOs for REST + internal use."""

from typing import List, Optional
from pydantic import BaseModel, Field


class StartupPipelineRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    task: str
    model: Optional[str] = None


class StartupPipelineResponse(BaseModel):
    background_narrative: str = ""
    inferred_state: str = ""
    long_term_context: str = ""
    knowledge_context: str = ""
    artifacts_context: str = ""
    tool_stats_context: str = ""
    search_labels: List[str] = Field(default_factory=list)
    search_query: str = ""
    complexity: str = ""


class RunCurationRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    mission_data_json: str
    model: Optional[str] = None


class RunCurationResponse(BaseModel):
    reflection: str = ""
    reflection_uuid: str = ""
    knowledge_count: int = 0
    artifact_count: int = 0
    events_compressed: bool = False
