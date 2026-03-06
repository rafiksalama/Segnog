"""Smart operations router — LLM-powered memory operations."""

import json
from fastapi import APIRouter, Request

from ..dependencies import get_episode_store, get_short_term, get_dragonfly

router = APIRouter()


@router.post("/smart/reinterpret-task")
async def reinterpret_task_endpoint(body: dict):
    """Reinterpret task into search labels, query, and complexity via DSPy."""
    from ...smart.reinterpret import reinterpret_task

    result = await reinterpret_task(
        task=body.get("task", ""),
        model=body.get("model"),
    )
    return {
        "search_labels": result.get("search_labels", []),
        "search_query": result.get("search_query", ""),
        "complexity": result.get("complexity_assessment", ""),
    }


@router.post("/smart/filter-results")
async def filter_results_endpoint(body: dict):
    """LLM-powered relevance filter for memory search results."""
    from ...smart.filter import filter_memory_results

    result = await filter_memory_results(
        task=body.get("task", ""),
        search_results=body.get("search_results", ""),
        model=body.get("model"),
        max_results=body.get("max_results", 5),
    )
    return {"filtered_results": result}


@router.post("/smart/infer-state")
async def infer_state_endpoint(body: dict):
    """LLM-powered state inference from task + memories."""
    from ...smart.infer_state import infer_state

    result = await infer_state(
        task=body.get("task", ""),
        retrieved_memories=body.get("retrieved_memories", ""),
        model=body.get("model"),
    )
    return {"state_description": result}


@router.post("/smart/synthesize-background")
async def synthesize_background_endpoint(body: dict, request: Request):
    """Synthesize background narrative from all memory sources."""
    from ...smart.synthesize import synthesize_background

    episode_store = get_episode_store(request)
    group_id = body.get("group_id", "default")
    episode_store._group_id = group_id

    result = await synthesize_background(
        task=body.get("task", ""),
        long_term_context=body.get("long_term_context", ""),
        tool_stats_context=body.get("tool_stats_context", ""),
        inferred_state=body.get("state_description", ""),
        model=body.get("model"),
        knowledge_context=body.get("knowledge_context", ""),
        artifacts_context=body.get("artifacts_context", ""),
        episode_store=episode_store,
    )
    return result


@router.post("/smart/generate-reflection")
async def generate_reflection_endpoint(body: dict):
    """Generate post-mission reflection."""
    from ...smart.reflect import generate_reflection

    mission_data = body.get("mission_data_json", "{}")
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    result = await generate_reflection(mission_data)
    return {"reflection": result}


@router.post("/smart/extract-knowledge")
async def extract_knowledge_endpoint(body: dict):
    """Extract knowledge entries from mission data via DSPy."""
    from ...smart.extract_knowledge import extract_knowledge

    mission_data = body.get("mission_data_json", "{}")
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    entries = await extract_knowledge(
        mission_data=mission_data,
        reflection=body.get("reflection", ""),
        model=body.get("model"),
    )
    return {"entries_json": json.dumps(entries)}


@router.post("/smart/extract-artifacts")
async def extract_artifacts_endpoint(body: dict):
    """Extract artifact entries from mission data via DSPy."""
    from ...smart.extract_artifacts import extract_artifacts

    mission_data = body.get("mission_data_json", "{}")
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    entries = await extract_artifacts(
        mission_data=mission_data,
        model=body.get("model"),
    )
    return {"entries_json": json.dumps(entries)}


@router.post("/smart/compress-events")
async def compress_events_endpoint(body: dict, request: Request):
    """Compress old events into episode summary."""
    from ...smart.compress import compress_events

    short_term = get_short_term(request)
    episode_store = get_episode_store(request)
    group_id = body.get("group_id", "default")
    workflow_id = body.get("workflow_id", "default")

    dragonfly = get_dragonfly(request)
    dragonfly.set_scope(group_id=group_id, workflow_id=workflow_id)

    result = await compress_events(
        short_term_memory=short_term,
        episode_store=episode_store,
        run_id=body.get("run_id", ""),
        state_description=body.get("state_description", ""),
        model=body.get("model"),
    )
    return result
