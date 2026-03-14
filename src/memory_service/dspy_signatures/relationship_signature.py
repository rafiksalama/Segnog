"""
DSPy Signature for Relationship Extraction

Extracts typed relationships between entities from text, using Schema.org
property names as predicates. The full Schema.org reference is injected at call time.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

import dspy


class RelationshipEntryModel(BaseModel):
    """A single extracted relationship triple.

    All fields are Optional so that Pydantic never hard-fails on a
    partially-formed LLM output. The extractor filters out incomplete
    entries before storage.
    """
    subject: Optional[str] = Field(
        default=None,
        description="The subject entity name (complete form, e.g., 'Caroline', 'Julia Horrocks')"
    )
    subject_type: Optional[str] = Field(
        default="Thing",
        description="Schema.org class name of the subject entity (e.g., 'Person', 'Organization')"
    )
    predicate: Optional[str] = Field(
        default=None,
        description="Schema.org property name in camelCase (e.g., 'worksFor', 'parent', "
                    "'homeLocation', 'knows', 'memberOf', 'alumniOf'). "
                    "Use the exact property name from the Schema.org reference."
    )
    object: Optional[str] = Field(
        default=None,
        description="The object entity name (complete form)"
    )
    object_type: Optional[str] = Field(
        default="Thing",
        description="Schema.org class name of the object entity"
    )
    confidence: Optional[float] = Field(
        default=1.0,
        description="Confidence in this relationship: 0.0 (speculative) to 1.0 (explicitly stated)"
    )


class RelationshipExtractionResult(BaseModel):
    """Structured result from relationship extraction."""
    relationships: List[RelationshipEntryModel] = Field(
        default_factory=list,
        description="All entity relationships found in the text. "
                    "Extract every stated relationship — family, professional, locational, social. "
                    "Use Schema.org property names as predicates."
    )


class RelationshipExtractionSignature(dspy.Signature):
    """You are a relationship extraction specialist. Extract all entity relationships
    from the text and express each as a (subject, predicate, object) triple using
    Schema.org property names as predicates.

    Guidelines:
    - Extract EVERY stated relationship: family, professional, locational, social, ownership
    - Use the exact Schema.org property name (camelCase) from the reference
    - Subject and object must be named entities (not pronouns)
    - subject_type and object_type must be Schema.org class names from the reference
    - Confidence: 1.0 for explicitly stated facts, lower for inferences
    - Do NOT invent relationships not stated in the text
    - Prefer specific predicates: use 'parent' not 'relatedTo', 'worksFor' not 'knows'

    Examples:
      "Caroline's mum Julia is a nurse at the NHS"
        → subject=Caroline, predicate=parent, object=Julia Horrocks
        → subject=Julia Horrocks, predicate=worksFor, object=NHS

      "Melanie works at Spotify"
        → subject=Melanie, predicate=worksFor, object=Spotify

      "Caroline lives in Stockholm"
        → subject=Caroline, predicate=homeLocation, object=Stockholm
    """

    schema_reference: str = dspy.InputField(
        desc="Full Schema.org property reference with domain/range/inverse info. "
             "Use the exact property names and class names listed here."
    )

    conversation_text: str = dspy.InputField(
        desc="The text to extract relationships from"
    )

    result: RelationshipExtractionResult = dspy.OutputField(
        desc="All entity relationships expressed as Schema.org triples"
    )
