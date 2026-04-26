"""Curation workflow definition — DAG of extraction stages.

```
 reflection (sync)
     |
     v
 knowledge (sync)
     |
     |----------+----------+
     v          v          v
 artifacts  causals    ontology
 (async)    (async)    (async)
```
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict

from .base import Stage, Workflow

logger = logging.getLogger(__name__)


# ── Stage handlers ────────────────────────────────────────────────────────────


async def handle_reflection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Step 1: Generate reflection from mission data."""
    from ..intelligence.synthesis.reflect import generate_reflection

    mission_data = payload["mission_data"]
    model = payload.get("model")
    group_id = payload.get("group_id")

    try:
        sections = await generate_reflection(mission_data, model=model, group_id=group_id)
        reflection = sections.get("reflection", "")
        return {"reflection": reflection, "sections": sections}
    except Exception as e:
        logger.warning("Reflection generation failed (non-critical): %s", e)
        return {
            "reflection": f"Mission completed with status={mission_data.get('status', '')}.",
            "sections": {},
        }


async def handle_knowledge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Step 3: Extract knowledge entries (depends on reflection)."""
    from ..intelligence.extract.knowledge import extract_knowledge

    mission_data = payload["mission_data"]
    model = payload.get("model")
    data_source_type = mission_data.get("data_source_type", "mission")

    # Get reflection from the previous sync stage result
    reflection_result = payload.get("reflection_result", {})
    reflection = reflection_result.get("reflection", "")

    try:
        entries = await extract_knowledge(
            mission_data=mission_data,
            reflection=reflection,
            model=model,
            data_source_type=data_source_type,
        )
        return {"entries": entries}
    except Exception as e:
        logger.warning("Knowledge extraction failed (non-critical): %s", e)
        return {"entries": []}


async def handle_artifacts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Step 5: Extract and store artifact entries."""
    from ..intelligence.extract.artifacts import extract_artifacts

    mission_data = payload["mission_data"]
    model = payload.get("model")

    try:
        entries = await extract_artifacts(mission_data=mission_data, model=model)
        if entries:
            art_store = payload.get("artifact_store")
            if art_store:
                await art_store.store_artifacts(
                    entries=entries,
                    source_mission=mission_data.get("task", ""),
                    mission_status=mission_data.get("status", ""),
                    source_episode_uuid=payload.get("reflection_uuid", ""),
                )
            logger.info("Async artifacts: stored %d entries", len(entries))
        return {"artifact_count": len(entries)}
    except Exception as e:
        logger.warning("Artifact extraction failed (non-critical): %s", e)
        return {"artifact_count": 0}


async def handle_causals(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Step 7b: Extract and store causal claims."""
    from ..intelligence.extract.causals import extract_causal_claims

    causal_source = payload["mission_data"].get("output", "")
    causal_store = payload.get("causal_store")
    group_id = payload.get("group_id", "default")

    if not causal_source:
        return {"causal_count": 0}

    try:
        claims = await extract_causal_claims(causal_source)
        stored = 0
        if causal_store:
            for claim in claims:
                try:
                    await causal_store.upsert_claim(
                        cause_summary=claim["cause"],
                        effect_summary=claim["effect"],
                        mechanism=claim.get("mechanism", ""),
                        confidence=claim.get("confidence", 0.8),
                        causal_type=claim.get("causal_type", "causes"),
                        cause_entity=claim.get("cause_norm"),
                        effect_entity=claim.get("effect_norm"),
                        group_id=group_id,
                    )
                    stored += 1
                except Exception:
                    pass

            if stored:
                try:
                    await causal_store.revise_beliefs(group_id)
                    await causal_store.auto_chain(group_id)
                except Exception as e:
                    logger.debug("Belief revision/chaining failed: %s", e)

        logger.info("Async causals: stored %d/%d claims", stored, len(claims))
        return {"causal_count": stored}
    except Exception as e:
        logger.warning("Causal extraction failed (non-critical): %s", e)
        return {"causal_count": 0}


async def handle_ontology(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Step 8: Run the ontology pipeline (heavy — 60+ LLM calls)."""
    from ..intelligence.graph.ontology_pipeline import update_group_ontology

    ontology_store = payload.get("ontology_store")
    if not ontology_store:
        return {}

    group_id = payload.get("group_id", "default")
    episodes = payload.get("episodes", [])
    combined_text = payload.get("combined_text", "")
    causal_store = payload.get("causal_store")

    try:
        await update_group_ontology(
            ontology_store=ontology_store,
            group_id=group_id,
            episodes=episodes,
            combined_text=combined_text,
            causal_store=causal_store,
        )
        logger.info("Async ontology: complete for '%s'", group_id)
    except Exception as e:
        logger.error("Async ontology failed for '%s': %s", group_id, e, exc_info=True)
    return {}


# ── Handler factories (for AsyncWorker store injection) ──────────────────────


def make_artifacts_handler(artifact_store):
    """Create a handler that injects a scoped ArtifactStore."""

    async def handler(payload: Dict[str, Any]) -> Dict[str, Any]:
        group_id = payload.get("group_id", "default")
        store = copy.copy(artifact_store)
        store._group_id = group_id
        payload["artifact_store"] = store
        return await handle_artifacts(payload)

    return handler


def make_causals_handler(causal_store):
    """Create a handler that injects the CausalClaimStore."""

    async def handler(payload: Dict[str, Any]) -> Dict[str, Any]:
        payload["causal_store"] = causal_store
        return await handle_causals(payload)

    return handler


def make_ontology_handler(ontology_store, causal_store, episode_store):
    """Create a handler that injects stores and fetches episodes from FalkorDB."""

    async def handler(payload: Dict[str, Any]) -> Dict[str, Any]:
        group_id = payload.get("group_id", "default")
        payload["ontology_store"] = ontology_store
        payload["causal_store"] = causal_store

        # Fetch episodes from FalkorDB if not already provided
        if not payload.get("episodes"):
            store = copy.copy(episode_store)
            store._group_id = group_id
            try:
                results = await store._graph.ro_query(
                    """MATCH (e:Episode {group_id: $gid})
                    WHERE coalesce(e.episode_type, 'raw') = 'raw'
                    RETURN e.uuid AS uuid, e.content AS content
                    ORDER BY e.created_at DESC
                    LIMIT 20""",
                    params={"gid": group_id},
                )
                episodes = [
                    {"uuid": row[0], "content": row[1] or ""}
                    for row in results.result_set
                    if row[0]
                ]
                payload["episodes"] = episodes
                if not payload.get("combined_text"):
                    payload["combined_text"] = "\n---\n".join(ep["content"] for ep in episodes)
            except Exception as e:
                logger.warning("Failed to fetch episodes for ontology: %s", e)

        return await handle_ontology(payload)

    return handler


# ── Workflow factory ──────────────────────────────────────────────────────────


def curation_workflow() -> Workflow:
    """Return the curation extraction pipeline as a DAG."""
    return Workflow(
        name="curation",
        stages=[
            Stage(
                name="reflection",
                handler=handle_reflection,
                sync=True,
                depends_on=[],
                timeout=120,
            ),
            Stage(
                name="knowledge",
                handler=handle_knowledge,
                sync=True,
                depends_on=["reflection"],
                timeout=120,
            ),
            Stage(
                name="artifacts",
                handler=handle_artifacts,
                sync=False,
                depends_on=["knowledge"],
            ),
            Stage(
                name="causals",
                handler=handle_causals,
                sync=False,
                depends_on=["knowledge"],
            ),
            Stage(
                name="ontology",
                handler=handle_ontology,
                sync=False,
                depends_on=["knowledge"],
            ),
        ],
    )
