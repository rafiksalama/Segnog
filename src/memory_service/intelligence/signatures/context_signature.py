"""
DSPy Signature for Context Summarization

Summarizes session context relevant to the current observation.
Used by the observe endpoint to return comprehensive, lossless context.
"""

from pydantic import BaseModel, Field

import dspy


class ContextSummaryResult(BaseModel):
    """Comprehensive context relevant to the current observation."""

    summary: str = Field(
        description="Thorough summary of ALL session context relevant to the current "
        "observation. PRESERVE every specific detail: exact dates "
        "(e.g. '7 May 2023', not 'recently'), full names, numbers, "
        "book/movie titles, locations, events, preferences, and relationships. "
        "Organize by topic or chronologically. Use as many sentences as needed "
        "to capture all relevant information — do not compress or generalize. "
        "If nothing is relevant, say so briefly. "
        "Do NOT repeat the current observation itself."
    )


class ContextSummarizationSignature(dspy.Signature):
    """You are a context compiler for an AI agent's memory system.

    Your job is to read the session context (prior observations, retrieved
    memories, and knowledge entries) and compile ALL information relevant
    to the current observation into a comprehensive summary.

    CRITICAL — preserve all details:
    - Exact dates and times (never paraphrase '7 May 2023' as 'recently')
    - Full names of people, places, organizations
    - Specific numbers, quantities, durations
    - Book titles, event names, activity names
    - Stated preferences, opinions, plans
    - Relationships between people
    - Temporal sequences (what happened before/after what)

    Structure:
    - Group related facts together by topic
    - Distinguish between direct observations and retrieved memories/knowledge
    - Include ALL relevant facts — it is better to include too much than too little
    - Do NOT repeat the current observation itself
    """

    current_observation: str = dspy.InputField(desc="The raw observation text just received")
    session_context: str = dspy.InputField(
        desc="Formatted session entries (observations, memories, knowledge) "
        "sorted chronologically with source labels"
    )

    result: ContextSummaryResult = dspy.OutputField(
        desc="Comprehensive summary preserving all relevant details"
    )
