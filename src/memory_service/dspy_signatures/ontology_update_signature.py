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
       (e.g., session dated "15 March 2024" + "last week" → "week of 8-14 March 2024")
    4. NEVER invent or hallucinate facts not present in either the existing summary or episode text
    5. Write in neutral, factual third-person style. Present tense for states, past tense for events
    6. Be SPECIFIC: use full names, exact dates, job titles, locations — not vague descriptions
    7. If the existing summary is empty, synthesize a fresh summary from the episode text only
    8. If the entity name is NOT mentioned in the episode text, return the existing summary unchanged
    9. Output ONLY the updated summary text — no explanations, headers, or bullet points

    Example output for a Person:
    "Marco Bellini is an Italian documentary filmmaker based in Barcelona. He works
    for Lighthouse Films and directed the documentary 'The Silence of Glaciers', which
    won the Sundance Documentary Prize. His sister is Dr. Priya Nair, a cardiologist
    at Riverside Medical Center in Chicago. In March 2024, Marco premiered his film at
    the North Star Film Festival."

    Example output for an Organization:
    "Riverside Medical Center is a hospital located in Chicago, Illinois. It employs
    Dr. Priya Nair as a cardiologist. The center specializes in cardiac care and has
    been a teaching affiliate of Westbrook University since 2018."

    Example output for a CreativeWork:
    "'The Silence of Glaciers' is a documentary film directed by Marco Bellini and
    produced by Lighthouse Films. It premiered at the North Star Film Festival in
    March 2024 and won the Sundance Documentary Prize."
    """

    entity_name: str = dspy.InputField(
        desc="The display name of the entity being summarized "
             "(e.g., 'Marco Bellini', 'Riverside Medical Center', 'The Silence of Glaciers')"
    )

    schema_type: str = dspy.InputField(
        desc="Most specific Schema.org class of the entity "
             "(e.g., 'Person', 'Hospital', 'Corporation', 'Movie', 'Festival', 'MusicGroup', 'City')"
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
