"""
DSPy Signature for Entity Extraction

Extracts named entities from conversation/mission text and maps them to
Schema.org class names. The full Schema.org reference is injected into
the prompt at call time via the `schema_reference` input field.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

import dspy


class EntityEntryModel(BaseModel):
    """A single extracted entity.

    Both fields are Optional so partial LLM responses don't hard-fail.
    The extractor filters incomplete entries before storage.
    """
    name: Optional[str] = Field(
        default=None,
        description="The entity name as it appears in text. "
                    "Use the most complete proper name mentioned (e.g., 'Julia Horrocks' not 'Julia'). "
                    "Must be a proper noun — names of specific people, places, organizations, events."
    )
    schema_type: Optional[str] = Field(
        default="Thing",
        description="The Schema.org class name for this entity (e.g., 'Person', 'Organization', "
                    "'Place', 'Event', 'Hospital', 'CollegeOrUniversity', 'Movie', 'Product', 'Animal'). "
                    "Pick the most specific Schema.org class from the reference. "
                    "Use 'Thing' only as a last resort."
    )


class EntityExtractionResult(BaseModel):
    """Structured result from entity extraction."""
    entities: List[EntityEntryModel] = Field(
        default_factory=list,
        description="All named entities found in the text mapped to Schema.org class names. "
                    "Include people, organizations, places, events, and significant named objects. "
                    "Be thorough — extract every entity that could be useful for retrieval."
    )


class EntityExtractionSignature(dspy.Signature):
    """You are an entity extraction specialist. Extract all named entities from the
    text and classify each using the exact Schema.org class name from the reference below.

    EXTRACT these entity types:
    - People: full names (e.g., 'Caroline', 'Julia Horrocks', 'Melanie')
    - Organizations: companies, hospitals, schools (e.g., 'NHS', 'Spotify', 'LGBTQ support group')
    - Places: cities, countries, buildings (e.g., 'Stockholm', 'Sweden', 'London')
    - Events: specific named events (e.g., 'Emma's wedding', 'school play')
    - Animals/Pets: named pets (e.g., 'Luna', 'Oliver') → use 'Animal' schema type
    - Products/Works: named books, films, albums with proper titles

    DO NOT EXTRACT:
    - Generic noun phrases or descriptions ('the store', 'a school', 'some event')
    - Image captions or photo descriptions (e.g., 'a woman in a garden', 'family photo')
    - Entities with more than 4 words in their name (likely image descriptions, not entities)
    - Pronouns or vague references ('he', 'she', 'someone', 'they')
    - Occupations or roles without a specific name ('a nurse', 'a teacher')
    - Adjectives or abstract concepts ('happiness', 'success', 'support')

    Guidelines:
    - Use the most complete name form (prefer 'Julia Horrocks' over 'Julia' when both appear)
    - Pick the MOST SPECIFIC Schema.org class that applies (e.g., 'Hospital' over 'Organization')
    - Use exact camelCase class names from the Schema.org reference
    - Name pets and animals as 'Animal' schema type
    - Only use 'Thing' when absolutely no other class fits
    """

    schema_reference: str = dspy.InputField(
        desc="Full Schema.org class and property reference. Use the exact class names listed here."
    )

    conversation_text: str = dspy.InputField(
        desc="The text to extract entities from"
    )

    extraction: EntityExtractionResult = dspy.OutputField(
        desc="All named entities with their Schema.org class names. "
             "Only include entities that are proper nouns with at most 4 words in the name."
    )
