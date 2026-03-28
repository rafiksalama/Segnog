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

_SYSTEM_PROMPT = """You write factual entity summaries. Output ONLY the summary text — nothing else.

CRITICAL: Never write "I cannot", "I don't see", "Let me", "I need to", "Based on the context", or any meta-commentary. If the entity is not in the text, output the existing summary verbatim.

Rules:
1. PRESERVE every fact from the existing summary
2. ADD new facts from the episode text about this entity
3. NEVER invent facts
4. Third person, neutral, factual. Present tense for states, past tense for events
5. Be specific: names, dates, titles, locations
6. 2-8 sentences. No headers, bullets, or explanations."""


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

        # Reject responses with LLM meta-commentary or tool calls
        _REJECT_PATTERNS = [
            "I cannot", "I don't see", "I'm checking", "I should",
            "Let me", "I need to", "Action:", "web_search", "```",
            "I'll run", "Based on the context provided, I don't",
            "I cannot complete", "two required inputs",
        ]
        if any(p in updated for p in _REJECT_PATTERNS):
            logger.warning(
                "Ontology summary rejected for '%s': contains LLM meta-commentary",
                entity_name,
            )
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
