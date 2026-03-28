"""Smart operations router — LLM-powered memory operations."""

import json
import logging

from fastapi import APIRouter, Request

from ..dependencies import get_episode_store_for, get_short_term, get_dragonfly, get_ontology_store
from ..dto.smart import (
    ReinterpretTaskRequest,
    FilterResultsRequest,
    InferStateRequest,
    SynthesizeBackgroundRequest,
    GenerateReflectionRequest,
    ExtractKnowledgeRequest,
    ExtractArtifactsRequest,
    ExtractRelationshipsRequest,
    UpdateOntologyNodeRequest,
    SearchOntologyNodesRequest,
    CompressEventsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/smart/reinterpret-task")
async def reinterpret_task_endpoint(body: ReinterpretTaskRequest):
    """Reinterpret task into search labels, query, and complexity via DSPy."""
    from ....intelligence.evaluation.reinterpret import reinterpret_task

    result = await reinterpret_task(task=body.task, model=body.model)
    return {
        "search_labels": result.get("search_labels", []),
        "search_query": result.get("search_query", ""),
        "complexity": result.get("complexity_assessment", ""),
    }


@router.post("/smart/filter-results")
async def filter_results_endpoint(body: FilterResultsRequest):
    """LLM-powered relevance filter for memory search results."""
    from ....intelligence.evaluation.filter import filter_memory_results

    result = await filter_memory_results(
        task=body.task,
        search_results=body.search_results,
        model=body.model,
        max_results=body.max_results,
    )
    return {"filtered_results": result}


@router.post("/smart/infer-state")
async def infer_state_endpoint(body: InferStateRequest):
    """LLM-powered state inference from task + memories."""
    from ....intelligence.evaluation.infer_state import infer_state

    result = await infer_state(
        task=body.task,
        retrieved_memories=body.retrieved_memories,
        model=body.model,
    )
    return {"state_description": result}


@router.post("/smart/synthesize-background")
async def synthesize_background_endpoint(body: SynthesizeBackgroundRequest, request: Request):
    """Synthesize background narrative from all memory sources."""
    from ....intelligence.synthesis.synthesize import synthesize_background

    episode_store = get_episode_store_for(request, body.group_id)

    result = await synthesize_background(
        task=body.task,
        long_term_context=body.long_term_context,
        tool_stats_context=body.tool_stats_context,
        inferred_state=body.state_description,
        model=body.model,
        knowledge_context=body.knowledge_context,
        artifacts_context=body.artifacts_context,
        episode_store=episode_store,
    )
    return result


@router.post("/smart/generate-reflection")
async def generate_reflection_endpoint(body: GenerateReflectionRequest):
    """Generate post-mission reflection."""
    from ....intelligence.synthesis.reflect import generate_reflection

    mission_data = body.mission_data_json
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    group_id = getattr(body, "group_id", None) or mission_data.get("group_id")
    result = await generate_reflection(mission_data, model=body.model, group_id=group_id)
    return {"reflection": result}


@router.post("/smart/extract-knowledge")
async def extract_knowledge_endpoint(body: ExtractKnowledgeRequest):
    """Extract knowledge entries from mission data via DSPy."""
    from ....intelligence.extract.knowledge import extract_knowledge

    mission_data = body.mission_data_json
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    entries = await extract_knowledge(
        mission_data=mission_data,
        reflection=body.reflection,
        model=body.model,
    )
    return {"entries_json": json.dumps(entries)}


@router.post("/smart/extract-artifacts")
async def extract_artifacts_endpoint(body: ExtractArtifactsRequest):
    """Extract artifact entries from mission data via DSPy."""
    from ....intelligence.extract.artifacts import extract_artifacts

    mission_data = body.mission_data_json
    if isinstance(mission_data, str):
        mission_data = json.loads(mission_data)
    entries = await extract_artifacts(mission_data=mission_data, model=body.model)
    return {"entries_json": json.dumps(entries)}


@router.post("/smart/extract-relationships")
async def extract_relationships_endpoint(body: ExtractRelationshipsRequest):
    """Extract Schema.org-typed relationships from text using DSPy.

    Returns:
      relationships (list): List of {subject, subject_type, predicate, object, object_type, confidence}.
    """
    from ....intelligence.extract.relationships import extract_relationships

    rels = await extract_relationships(content=body.text, model=body.model)
    return {
        "relationships": [
            {
                "subject": r["subject"],
                "subject_type": r["subject_type"],
                "predicate": r["predicate"],
                "object": r["object"],
                "object_type": r["object_type"],
                "confidence": r["confidence"],
            }
            for r in rels
        ]
    }


@router.post("/smart/update-ontology-node")
async def update_ontology_node_endpoint(body: UpdateOntologyNodeRequest, request: Request):
    """Update an OntologyNode's prose summary using DSPy."""
    from ....intelligence.graph.update_ontology import update_ontology_summary

    updated_summary = await update_ontology_summary(
        entity_name=body.entity_name,
        schema_type=body.schema_type,
        existing_summary=body.existing_summary,
        new_episode_text=body.new_episode_text,
        model=body.model,
    )

    upserted_uuid = None
    if body.group_id:
        try:
            ontology_store = get_ontology_store(request)
            upserted_uuid = await ontology_store.upsert_node(
                name=body.entity_name,
                schema_type=body.schema_type,
                display_name=body.entity_name,
                summary=updated_summary,
                group_id=body.group_id,
            )
        except Exception as e:
            logger.warning("update-ontology-node: upsert failed: %s", e)

    return {"updated_summary": updated_summary, "uuid": upserted_uuid}


@router.post("/smart/search-ontology-nodes")
async def search_ontology_nodes_endpoint(body: SearchOntologyNodesRequest, request: Request):
    """Vector search over OntologyNode summary embeddings."""
    ontology_store = get_ontology_store(request)

    try:
        embedding = await ontology_store._embed(body.query)
        nodes = await ontology_store.search_nodes(
            embedding=embedding,
            top_k=body.top_k,
            group_id=body.group_id,
            min_score=body.min_score,
        )
        return {"nodes": nodes}
    except Exception as e:
        logger.warning("search-ontology-nodes failed: %s", e)
        return {"nodes": []}


@router.post("/smart/compress-events")
async def compress_events_endpoint(body: CompressEventsRequest, request: Request):
    """Compress old events into episode summary."""
    from ....intelligence.synthesis.compress import compress_events

    short_term = get_short_term(request)
    episode_store = get_episode_store_for(request, body.group_id)

    dragonfly = get_dragonfly(request)
    dragonfly.set_scope(group_id=body.group_id, workflow_id=body.workflow_id)

    result = await compress_events(
        short_term_memory=short_term,
        episode_store=episode_store,
        run_id=body.run_id,
        state_description=body.state_description,
        model=body.model,
    )
    return result
