"""State DTOs for REST + internal use."""

from typing import Optional
from pydantic import BaseModel


class PersistExecutionStateRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    state_description: str
    iteration: int = 0
    plan_json: Optional[str] = None
    judge_json: Optional[str] = None


class PersistExecutionStateResponse(BaseModel):
    success: bool


class GetExecutionStateResponse(BaseModel):
    state_description: str = ""
    iteration: int = 0
    plan_json: Optional[str] = None
    judge_json: Optional[str] = None
    found: bool = False


class UpdateToolStatsRequest(BaseModel):
    group_id: str = "default"
    workflow_id: str = "default"
    tool_name: str
    success: bool
    duration_ms: int = 0
    state_description: str = ""


class UpdateToolStatsResponse(BaseModel):
    success: bool


class GetToolStatsResponse(BaseModel):
    formatted_stats: str = ""
    raw_stats_json: str = "{}"


class GetMemoryContextResponse(BaseModel):
    formatted_context: str = ""
