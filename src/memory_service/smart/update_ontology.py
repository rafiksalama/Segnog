"""
Ontology Node Update — LLM-powered entity summary integration.

Takes an entity's existing prose summary and new episode text, and returns
an updated summary that integrates all new information while preserving
existing facts. Called once per entity per REM cycle.
"""

import logging
from typing import Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.ontology_update_signature import OntologyNodeUpdateSignature

logger = logging.getLogger(__name__)


async def update_ontology_summary(
    entity_name: str,
    schema_type: str,
    existing_summary: str,
    new_episode_text: str,
    model: Optional[str] = None,
) -> str:
    """
    Update an OntologyNode's prose summary by integrating new episode information.

    Args:
        entity_name:       Display name of the entity (e.g., 'Caroline').
        schema_type:       Schema.org class name (e.g., 'Person').
        existing_summary:  Current prose summary. Empty string if first update.
        new_episode_text:  New episode content to integrate.
        model:             Flash model identifier.

    Returns:
        Updated prose summary string. Falls back to existing_summary on error.
    """
    if not new_episode_text or len(new_episode_text.strip()) < 5:
        return existing_summary

    MAX_INPUT = 16000
    if len(new_episode_text) > MAX_INPUT:
        new_episode_text = new_episode_text[:MAX_INPUT]

    try:
        lm = configure_dspy_lm(model=model, temperature=0.2, max_tokens=4096)
        predictor = dspy.Predict(OntologyNodeUpdateSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(
                entity_name=entity_name,
                schema_type=schema_type,
                existing_summary=existing_summary or "",
                new_episode_text=new_episode_text,
            )

        raw = result.result.updated_summary
        updated = str(raw).strip() if raw else ""
        if not updated or len(updated) < 10:
            return existing_summary

        logger.info(
            "Updated OntologyNode summary for '%s' (%s): %d chars",
            entity_name,
            schema_type,
            len(updated),
        )
        return updated

    except Exception as e:
        logger.error("Ontology summary update failed for '%s': %s", entity_name, e)
        return existing_summary
