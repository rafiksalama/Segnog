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
        description="The subject entity name (complete form, e.g., 'Alex Rivera', 'Riverside Medical Center', "
                    "'The Silence of Glaciers')"
    )
    subject_type: Optional[str] = Field(
        default="Thing",
        description="Most specific Schema.org class of the subject entity "
                    "(e.g., 'Person', 'Hospital', 'Movie', 'MusicGroup', 'SportsTeam', "
                    "'Festival', 'ConferenceEvent', 'PodcastSeries', 'WebSite', 'Dataset'). "
                    "Note: 'Animal', 'Award', 'Podcast' are NOT Schema.org classes — "
                    "use 'Taxon', 'Intangible', 'PodcastSeries' respectively."
    )
    predicate: Optional[str] = Field(
        default=None,
        description="Schema.org property name in camelCase. Common predicates by domain:\n"
                    "Person → *: 'worksFor', 'homeLocation', 'birthPlace', 'birthDate', "
                    "'parent', 'children', 'sibling', 'spouse', 'knows', 'colleague', "
                    "'alumniOf', 'memberOf', 'founder', 'nationality', 'jobTitle', "
                    "'hasCredential', 'owns', 'affiliation', 'performerIn', 'knowsLanguage'.\n"
                    "CreativeWork → *: 'director', 'author', 'byArtist', 'publisher', "
                    "'award' (value=Text, not entity), 'datePublished', 'dateCreated', "
                    "'about', 'genre', 'inLanguage', 'isPartOf', 'recordedAt', "
                    "'mentions', 'locationCreated'.\n"
                    "Organization → *: 'location', 'founder', 'foundingDate', 'employee', "
                    "'member', 'subOrganization', 'parentOrganization', 'areaServed', "
                    "'legalName', 'department'.\n"
                    "Event → *: 'location', 'eventVenue', 'organizer', 'performer', "
                    "'startDate', 'endDate', 'superEvent', 'subEvent', 'attendee'.\n"
                    "Place → *: 'containedIn', 'containsPlace', 'address'.\n"
                    "MedicalCondition → *: 'cause', 'signOrSymptom', 'possibleTreatment', "
                    "'riskFactor', 'drug', 'associatedAnatomy'.\n"
                    "MedicalProcedure/MedicalTherapy → *: 'drug', 'bodyLocation', 'followup'.\n"
                    "Physician/Hospital/MedicalClinic → *: 'hospitalAffiliation', 'medicalSpecialty'.\n"
                    "Patient → *: 'diagnosis', 'drug'.\n"
                    "Note: 'award', 'startDate', 'endDate', 'datePublished', 'dateCreated', "
                    "'foundingDate', 'birthDate' have Date/Text range — their object is a "
                    "literal value, not a named entity node.\n"
                    "Use the exact property name from the Schema.org reference."
    )
    object: Optional[str] = Field(
        default=None,
        description="The object entity name (complete form)"
    )
    object_type: Optional[str] = Field(
        default="Thing",
        description="Most specific Schema.org class of the object entity. "
                    "Same rules as subject_type — use the most specific real Schema.org class."
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
    - Extract EVERY stated relationship: family, professional, locational, creative, social, ownership
    - Use the exact Schema.org property name (camelCase) from the reference
    - Subject and object must be named entities (not pronouns)
    - subject_type and object_type must be the most specific Schema.org class from the reference
    - Confidence: 1.0 for explicitly stated facts, lower for inferences
    - Do NOT invent relationships not stated in the text
    - Prefer specific predicates: 'parent' not 'relatedTo', 'worksFor' not 'knows',
      'director' not 'creator', 'byArtist' not 'creator' for music

    Symmetric predicates (extract only once, the system infers the reverse):
    - sibling, spouse, knows, colleague

    Examples:
      "Marco Bellini, Dr. Priya Nair's brother, directed The Silence of Glaciers for Lighthouse Films"
        → subject=Marco Bellini (Person), predicate=sibling, object=Dr. Priya Nair (Person)
        → subject=Marco Bellini (Person), predicate=director, object=The Silence of Glaciers (Movie)
        → subject=Marco Bellini (Person), predicate=worksFor, object=Lighthouse Films (Corporation)

      "Alex Rivera joined Helix Systems as a senior engineer"
        → subject=Alex Rivera (Person), predicate=worksFor, object=Helix Systems (Corporation)

      "Riverside Medical Center is located in Chicago"
        → subject=Riverside Medical Center (Hospital), predicate=location, object=Chicago (City)

      "The Silence of Glaciers won the Sundance Documentary Prize"
        → subject=The Silence of Glaciers (Movie), predicate=award, object="Sundance Documentary Prize"
          (NOTE: 'award' has Text range — the object is the award name as a literal, NOT a node)
    """

    schema_reference: str = dspy.InputField(
        desc="Full Schema.org property reference with domain/range/inverse info. "
             "Use the exact property names and class names listed here."
    )

    source_text: str = dspy.InputField(
        desc="The text to extract relationships from"
    )

    result: RelationshipExtractionResult = dspy.OutputField(
        desc="All entity relationships expressed as Schema.org triples"
    )
