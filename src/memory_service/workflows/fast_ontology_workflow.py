"""Fast ontology DAG — coverage-first pipeline for groups with no ontology data.

Single async stage:
  fast_ontology → Pass 2 only, auto summaries, post-hoc ABOUT edges, auto_chain

Dispatched by the REM worker when it discovers groups with no ABOUT edges.
Processed by PriorityAsyncWorker (drains fast queue before normal queue).
"""

import logging
from typing import Any, Dict

from .base import Stage, Workflow

logger = logging.getLogger(__name__)


def fast_ontology_workflow() -> Workflow:
    """Return the fast coverage ontology pipeline as a single-stage DAG."""
    return Workflow(
        name="fast_ontology",
        stages=[
            Stage(
                name="fast_ontology",
                handler=_placeholder_handler,
                sync=False,
                depends_on=[],
            ),
        ],
    )


# Placeholder — the real handler is created by make_fast_ontology_handler()
async def _placeholder_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {}


def make_fast_ontology_handler(ontology_store, causal_store, episode_store):
    """Create the fast coverage ontology handler with injected stores.

    The handler:
    1. Fetches raw episodes for the group from FalkorDB
    2. Runs fast_coverage_ontology() (Pass 2 only, auto summaries)
    3. Creates ABOUT edges via embedding similarity
    """
    import copy

    async def handle_fast_ontology(payload: Dict[str, Any]) -> Dict[str, Any]:
        group_id = payload.get("group_id", "default")

        # Fetch episodes from FalkorDB
        episodes = []
        combined_text = ""
        store = copy.copy(episode_store)
        store._group_id = group_id
        try:
            results = await store._graph.ro_query(
                """MATCH (e:Episode {group_id: $gid})
                WHERE coalesce(e.episode_type, 'raw') = 'raw'
                RETURN e.uuid AS uuid, e.content AS content
                ORDER BY e.created_at ASC
                LIMIT 20""",
                params={"gid": group_id},
            )
            episodes = [
                {"uuid": row[0], "content": row[1] or ""} for row in results.result_set if row[0]
            ]
            combined_text = "\n---\n".join(ep["content"] for ep in episodes if ep["content"])
        except Exception as e:
            logger.warning("Failed to fetch episodes for fast ontology: %s", e)

        if not episodes:
            logger.warning("Fast ontology: no episodes found for '%s'", group_id)
            return {"group_id": group_id, "coverage": False}

        # Fast coverage pipeline
        from ..intelligence.graph.ontology_pipeline import (
            create_about_edges_by_similarity,
            fast_coverage_ontology,
        )

        await fast_coverage_ontology(
            ontology_store=ontology_store,
            group_id=group_id,
            episodes=episodes,
            combined_text=combined_text,
            causal_store=causal_store,
        )

        # Post-hoc ABOUT edges via embedding similarity
        await create_about_edges_by_similarity(group_id, ontology_store)

        return {"group_id": group_id, "coverage": True}

    return handle_fast_ontology
