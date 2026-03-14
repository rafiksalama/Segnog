"""Smart operations router — LLM-powered memory operations."""

import json
import logging
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

from ..dependencies import get_episode_store, get_short_term, get_dragonfly, get_ontology_store

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
    result = await generate_reflection(mission_data, model=body.get("model"))
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


@router.post("/smart/extract-relationships")
async def extract_relationships_endpoint(body: dict):
    """Extract Schema.org-typed relationships from text using DSPy.

    Request body:
      text (str): The text to extract relationships from.
      group_id (str): Optional group_id for scoping (not used in extraction).
      model (str): Optional model override.

    Returns:
      relationships (list): List of {subject, subject_type, predicate, object, object_type, confidence}.
    """
    from ...smart.extract_relationships import extract_relationships

    rels = await extract_relationships(
        content=body.get("text", ""),
        model=body.get("model"),
    )
    # Return only the user-facing fields (no internal *_norm keys)
    return {
        "relationships": [
            {
                "subject":      r["subject"],
                "subject_type": r["subject_type"],
                "predicate":    r["predicate"],
                "object":       r["object"],
                "object_type":  r["object_type"],
                "confidence":   r["confidence"],
            }
            for r in rels
        ]
    }


@router.post("/smart/update-ontology-node")
async def update_ontology_node_endpoint(body: dict, request: Request):
    """Update an OntologyNode's prose summary using DSPy.

    Request body:
      entity_name (str): Display name of the entity (e.g., 'Caroline').
      schema_type (str): Schema.org class name (e.g., 'Person').
      existing_summary (str): Current prose summary. Empty string if first update.
      new_episode_text (str): New episode content to integrate.
      group_id (str): Optional group_id. If provided, also upserts the node.
      model (str): Optional model override.

    Returns:
      updated_summary (str): Updated prose summary.
    """
    from ...smart.update_ontology import update_ontology_summary

    entity_name = body.get("entity_name", "")
    schema_type = body.get("schema_type", "Thing")
    existing_summary = body.get("existing_summary", "")
    new_episode_text = body.get("new_episode_text", "")
    group_id = body.get("group_id")

    updated_summary = await update_ontology_summary(
        entity_name=entity_name,
        schema_type=schema_type,
        existing_summary=existing_summary,
        new_episode_text=new_episode_text,
        model=body.get("model"),
    )

    # Optionally upsert the node into the OntologyStore
    upserted_uuid = None
    if group_id:
        try:
            ontology_store = get_ontology_store(request)
            upserted_uuid = await ontology_store.upsert_node(
                name=entity_name,
                schema_type=schema_type,
                display_name=entity_name,
                summary=updated_summary,
                group_id=group_id,
            )
        except Exception as e:
            logger.warning("update-ontology-node: upsert failed: %s", e)

    return {
        "updated_summary": updated_summary,
        "uuid": upserted_uuid,
    }


@router.post("/smart/search-ontology-nodes")
async def search_ontology_nodes_endpoint(body: dict, request: Request):
    """Vector search over OntologyNode summary embeddings.

    Request body:
      query (str): Natural-language query to embed.
      group_id (str): Scope for the search.
      top_k (int): Max results to return (default 5).
      min_score (float): Minimum cosine similarity (default 0.3).

    Returns:
      nodes (list): [{uuid, name, schema_type, display_name, summary, score}]
    """
    ontology_store = get_ontology_store(request)
    group_id = body.get("group_id", "default")
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    min_score = float(body.get("min_score", 0.3))

    if not query:
        return {"nodes": []}

    try:
        embedding = await ontology_store._embed(query)
        nodes = await ontology_store.search_nodes(
            embedding=embedding,
            top_k=top_k,
            group_id=group_id,
            min_score=min_score,
        )
        return {"nodes": nodes}
    except Exception as e:
        logger.warning("search-ontology-nodes failed: %s", e)
        return {"nodes": []}


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
