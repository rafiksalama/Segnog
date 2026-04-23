"""Smart operation request DTOs."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ReinterpretTaskRequest(BaseModel):
    task: str = Field(..., min_length=1)
    model: Optional[str] = None


class FilterResultsRequest(BaseModel):
    task: str = Field(..., min_length=1)
    search_results: str = ""
    model: Optional[str] = None
    max_results: int = Field(5, ge=1, le=100)


class InferStateRequest(BaseModel):
    task: str = Field(..., min_length=1)
    retrieved_memories: str = ""
    model: Optional[str] = None


class SynthesizeBackgroundRequest(BaseModel):
    group_id: str = "default"
    task: str = Field(..., min_length=1)
    long_term_context: str = ""
    tool_stats_context: str = ""
    state_description: str = ""
    model: Optional[str] = None
    knowledge_context: str = ""
    artifacts_context: str = ""


class GenerateReflectionRequest(BaseModel):
    mission_data_json: Any = "{}"
    model: Optional[str] = None


class ExtractKnowledgeRequest(BaseModel):
    mission_data_json: Any = "{}"
    reflection: str = ""
    model: Optional[str] = None


class ExtractArtifactsRequest(BaseModel):
    mission_data_json: Any = "{}"
    model: Optional[str] = None


class ExtractRelationshipsRequest(BaseModel):
    text: str = Field(..., min_length=1)
    group_id: str = "default"
    model: Optional[str] = None


class UpdateOntologyNodeRequest(BaseModel):
    entity_name: str = Field(..., min_length=1)
    schema_type: str = "Thing"
    existing_summary: str = ""
    new_episode_text: str = Field(..., min_length=1)
    group_id: Optional[str] = None
    model: Optional[str] = None


class SearchOntologyNodesRequest(BaseModel):
    query: str = Field(..., min_length=1)
    group_id: Optional[str] = None
    top_k: int = Field(5, ge=1, le=100)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


class CompressEventsRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    run_id: str = ""
    state_description: str = ""
    model: Optional[str] = None
