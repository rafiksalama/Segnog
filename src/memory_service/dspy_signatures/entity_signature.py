"""
DSPy Signature for Entity Extraction

Extracts named entities (people, places, organizations, activities, etc.)
from conversation text for entity-aware memory retrieval.
"""

from typing import List
from pydantic import BaseModel, Field

import dspy


class EntityEntryModel(BaseModel):
    """A single extracted entity."""
    name: str = Field(
        description="The entity name as it appears in conversation. "
                    "Use the most complete form mentioned (e.g., 'Julia Horrocks' not 'Julia')."
    )
    entity_type: str = Field(
        description="One of: 'person', 'place', 'activity', 'organization', "
                    "'event', 'preference', 'item'"
    )


class EntityExtractionResult(BaseModel):
    """Structured result from entity extraction."""
    entities: List[EntityEntryModel] = Field(
        description="All named entities found in the text. Include people, places, "
                    "organizations, activities, events, and significant items or preferences. "
                    "Be thorough — extract every entity that could be useful for retrieval."
    )


class EntityExtractionSignature(dspy.Signature):
    """You are an entity extraction specialist. Extract all named entities from
    the conversation text that could be useful for memory retrieval.

    Entity types:
    - person: People mentioned by name ("Julia", "Dr. Smith")
    - place: Locations ("Paris", "the coffee shop on Main St")
    - organization: Companies, institutions ("Google", "MIT")
    - activity: Hobbies, recurring activities ("pottery class", "yoga")
    - event: Specific events ("the wedding", "last year's conference")
    - preference: Expressed preferences ("vegetarian", "prefers dark mode")
    - item: Significant objects or products ("the red bike", "iPhone 15")

    Guidelines:
    - Use the most complete name form available
    - Include both formal and informal references
    - Skip generic references ("he", "she", "they") unless clearly identifiable
    - For people, prefer full names when mentioned anywhere in the text
    """

    conversation_text: str = dspy.InputField(
        desc="The conversation text to extract entities from"
    )

    extraction: EntityExtractionResult = dspy.OutputField(
        desc="All named entities found in the conversation"
    )
