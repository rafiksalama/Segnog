"""
Ontology Node Update — LLM-powered entity summary integration.

Takes an entity's existing prose summary and new episode text, and returns
an updated summary that integrates all new information while preserving
existing facts. Called once per entity per REM cycle.
"""

import logging
from typing import Optional

from ..llm.client import llm_call

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge integration specialist. Maintain a living prose summary of a single entity by integrating new information.

RULES:
1. PRESERVE every fact in the existing summary — never remove or contradict them
2. ADD facts from the episode text that mention this entity
3. NEVER invent facts not present in the inputs
4. Write in neutral, factual third-person style (present tense for states, past tense for events)
5. Be SPECIFIC: full names, dates, titles, locations
6. If existing summary is empty, create a fresh summary from episode text
7. If entity is NOT mentioned in episode text, return existing summary unchanged
8. Output ONLY the updated summary — no headers, bullets, or explanations
9. 2-8 sentences."""


async def update_ontology_summary(
    entity_name: str,
    schema_type: str,
    existing_summary: str,
    new_episode_text: str,
    model: Optional[str] = None,
) -> str:
    """
    Update an OntologyNode's prose summary by integrating new episode information.

    Returns updated prose summary string. Falls back to existing_summary on error.
    """
    if not new_episode_text or len(new_episode_text.strip()) < 5:
        return existing_summary

    MAX_INPUT = 16000
    if len(new_episode_text) > MAX_INPUT:
        new_episode_text = new_episode_text[:MAX_INPUT]

    prompt = f"""Entity: {entity_name} (type: {schema_type})

Existing summary:
{existing_summary or "(no existing summary)"}

New episode text:
{new_episode_text}

Write the updated prose summary for {entity_name}:"""

    try:
        updated = await llm_call(
            prompt,
            model=model,
            temperature=0.2,
            max_tokens=2000,
            system_prompt=_SYSTEM_PROMPT,
        )
        updated = updated.strip()
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
