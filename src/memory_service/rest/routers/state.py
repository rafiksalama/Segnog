"""State router — execution state, tool stats, memory context."""

import json
import time
from fastapi import APIRouter, Request

from ...dto.state import (
    PersistExecutionStateRequest,
    PersistExecutionStateResponse,
    GetExecutionStateResponse,
    UpdateToolStatsRequest,
    UpdateToolStatsResponse,
    GetToolStatsResponse,
    GetMemoryContextResponse,
)
from ..dependencies import get_dragonfly, get_short_term

router = APIRouter()


@router.put("/state/execution", response_model=PersistExecutionStateResponse)
async def persist_execution_state(body: PersistExecutionStateRequest, request: Request):
    dragonfly = get_dragonfly(request)
    state_key = f"exec_state:{body.group_id}:{body.workflow_id}"
    mapping = {
        "state_description": body.state_description,
        "iteration": json.dumps(body.iteration),
        "updated_at": json.dumps(time.time()),
    }
    if body.plan_json:
        mapping["plan"] = body.plan_json
    if body.judge_json:
        mapping["judge"] = body.judge_json
    await dragonfly.hset(state_key, mapping)
    return PersistExecutionStateResponse(success=True)


@router.get("/state/execution", response_model=GetExecutionStateResponse)
async def get_execution_state(
    request: Request,
    group_id: str = "default",
    workflow_id: str = "default",
):
    dragonfly = get_dragonfly(request)
    state_key = f"exec_state:{group_id}:{workflow_id}"
    data = await dragonfly.hgetall(state_key)
    if not data:
        return GetExecutionStateResponse(found=False)
    # DragonflyDB auto-parses JSON values, so plan/judge may come back as dicts
    plan_val = data.get("plan")
    if isinstance(plan_val, dict):
        plan_val = json.dumps(plan_val)
    judge_val = data.get("judge")
    if isinstance(judge_val, dict):
        judge_val = json.dumps(judge_val)

    return GetExecutionStateResponse(
        state_description=data.get("state_description", ""),
        iteration=int(data.get("iteration", 0)),
        plan_json=plan_val,
        judge_json=judge_val,
        found=True,
    )


@router.post("/state/tool-stats", response_model=UpdateToolStatsResponse)
async def update_tool_stats(body: UpdateToolStatsRequest, request: Request):
    short_term = get_short_term(request)

    # Build state hash for keying
    state_hash = str(hash(body.state_description))[:8] if body.state_description else "default"
    stats_key = f"state:tool_stats:{body.tool_name}:{state_hash}"

    existing = await short_term.get(stats_key)
    if existing and isinstance(existing, dict):
        existing["attempts"] = existing.get("attempts", 0) + 1
        if body.success:
            existing["successes"] = existing.get("successes", 0) + 1
        else:
            existing["failures"] = existing.get("failures", 0) + 1
        existing["total_duration_ms"] = existing.get("total_duration_ms", 0) + body.duration_ms
        stats = existing
    else:
        stats = {
            "tool_name": body.tool_name,
            "attempts": 1,
            "successes": 1 if body.success else 0,
            "failures": 0 if body.success else 1,
            "total_duration_ms": body.duration_ms,
        }

    await short_term.save(stats_key, stats)
    return UpdateToolStatsResponse(success=True)


@router.get("/state/tool-stats", response_model=GetToolStatsResponse)
async def get_tool_stats(
    request: Request,
    group_id: str = "default",
    workflow_id: str = "default",
):
    dragonfly = get_dragonfly(request)
    all_state = await dragonfly.hgetall("state")

    tool_stats = {}
    for key, value in all_state.items():
        if key.startswith("state:tool_stats:"):
            parts = key.split(":")
            tool_name = parts[2] if len(parts) > 2 else "unknown"
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    continue
            if isinstance(value, dict):
                stat_data = value.get("value", value)
                if isinstance(stat_data, str):
                    try:
                        stat_data = json.loads(stat_data)
                    except Exception:
                        continue
                if tool_name not in tool_stats:
                    tool_stats[tool_name] = {
                        "attempts": 0, "successes": 0,
                        "failures": 0, "total_duration_ms": 0,
                    }
                for field in ("attempts", "successes", "failures", "total_duration_ms"):
                    tool_stats[tool_name][field] += stat_data.get(field, 0)

    # Format
    lines = []
    for tool, stats in sorted(tool_stats.items()):
        attempts = stats["attempts"]
        successes = stats["successes"]
        avg_ms = stats["total_duration_ms"] // max(attempts, 1)
        lines.append(f"  {tool}: {attempts} calls, {successes} ok, avg {avg_ms}ms")

    formatted = "\n".join(lines) if lines else "No tool stats available."

    return GetToolStatsResponse(
        formatted_stats=formatted,
        raw_stats_json=json.dumps(tool_stats),
    )


@router.get("/state/context", response_model=GetMemoryContextResponse)
async def get_memory_context(
    request: Request,
    group_id: str = "default",
    workflow_id: str = "default",
    event_limit: int = 5,
):
    dragonfly = get_dragonfly(request)
    dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)
    events = await dragonfly.get_recent_events(count=event_limit)

    lines = []
    for e in reversed(events):  # Oldest first for context
        etype = e.get("type", "")
        data = e.get("data", {})
        content = data.get("content", str(data)[:200]) if isinstance(data, dict) else str(data)[:200]
        lines.append(f"[{etype}] {content}")

    formatted = "\n".join(lines) if lines else "No recent events."

    return GetMemoryContextResponse(formatted_context=formatted)
