"""
DSPy Signature for OntologyNode Summary Update

Takes an entity's existing prose summary (may be empty) and new episode text,
and returns an updated summary that integrates all new information while
preserving all existing facts.

Called once per entity per REM cycle.
"""

from typing import Optional
from pydantic import BaseModel, Field

import dspy


class OntologyUpdateResult(BaseModel):
    """Updated entity summary."""
    updated_summary: Optional[str] = Field(
        default=None,
        description="Complete, updated prose summary of everything known about this entity. "
                    "MUST integrate all facts from the existing summary AND all new information "
                    "from the episode text. Never remove facts from the existing summary. "
                    "Write in third person, present tense for ongoing facts, past tense for events. "
                    "Be specific: include names, dates, places, roles. 2-8 sentences. "
                    "ONLY include facts mentioned in the provided texts — do not invent anything."
    )


class OntologyNodeUpdateSignature(dspy.Signature):
    """You are a knowledge integration specialist. Your job is to maintain a living
    prose summary of a single real-world entity by integrating new information from
    episode text into the existing summary.

    STRICT RULES (violations invalidate the output):
    1. PRESERVE every fact in the existing summary — never remove, contradict, or weaken them
    2. ADD every fact from the episode text that mentions or relates to this entity
    3. RESOLVE relative time references using session header dates in the episode text
       (e.g., session dated "9 June 2023" + "last week" → "week of 2-8 June 2023")
    4. NEVER invent or hallucinate facts not present in either the existing summary or episode text
    5. Write in neutral, factual third-person style. Present tense for states, past tense for events
    6. Be SPECIFIC: use full names, exact dates, job titles, locations — not vague descriptions
    7. If the existing summary is empty, synthesize a fresh summary from the episode text only
    8. If the entity name is NOT mentioned in the episode text, return the existing summary unchanged
    9. Output ONLY the updated summary text — no explanations, headers, or bullet points

    Example output for a Person:
    "Caroline is a Swedish woman in her early 30s living in Stockholm, Sweden.
    She works at Spotify as a music curator. Her mother is Julia Horrocks, an NHS
    nurse in London who has worked there for approximately 10 years. Caroline's best
    friend is Melanie, whom she met at university. In June 2023, she attended Emma's
    wedding in Gothenburg."

    Example output for an Organization:
    "The NHS (National Health Service) is the public healthcare system of the United
    Kingdom. Julia Horrocks has worked there as a nurse for approximately 10 years,
    based in London."
    """

    entity_name: str = dspy.InputField(
        desc="The display name of the entity being summarized (e.g., 'Caroline', 'Spotify')"
    )

    schema_type: str = dspy.InputField(
        desc="Schema.org class of the entity (e.g., 'Person', 'Organization', 'Place', 'Animal')"
    )

    existing_summary: str = dspy.InputField(
        desc="Current prose summary of the entity. Empty string if this is the first update. "
             "PRESERVE every fact here — never remove or contradict them."
    )

    new_episode_text: str = dspy.InputField(
        desc="New episode text. Extract all facts about the entity_name from here and add to the summary. "
             "If entity_name is not mentioned, return the existing_summary unchanged."
    )

    result: OntologyUpdateResult = dspy.OutputField(
        desc="Updated prose summary integrating all known information about the entity. "
             "Only facts from existing_summary and new_episode_text. No hallucinations."
    )
