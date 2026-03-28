"""
DSPy Signature for Causal Claim Extraction

Extracts causal relationships from text — "X caused Y", "X led to Y",
"because of X, Y happened". Each claim identifies cause/effect entities
with Schema.org typing and an optional mechanism.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

import dspy


class CausalClaimModel(BaseModel):
    """A single extracted causal assertion."""

    cause: Optional[str] = Field(
        default=None,
        description="The cause entity or event (e.g., 'heavy rain', 'John's promotion', 'budget cuts')",
    )
    cause_type: Optional[str] = Field(
        default="Thing",
        description="Schema.org class of the cause (e.g., 'Event', 'Person', 'Organization', 'Action')",
    )
    effect: Optional[str] = Field(
        default=None,
        description="The effect entity or event (e.g., 'flooding', 'relocation to NYC', 'team layoffs')",
    )
    effect_type: Optional[str] = Field(
        default="Thing",
        description="Schema.org class of the effect",
    )
    mechanism: Optional[str] = Field(
        default=None,
        description="How or why the cause produces the effect (brief explanation)",
    )
    confidence: Optional[float] = Field(
        default=0.8,
        description="Confidence: 1.0 for explicitly stated causation, "
        "0.7-0.9 for strongly implied, 0.3-0.6 for speculative",
    )
    temporal_marker: Optional[str] = Field(
        default=None,
        description="Temporal relationship: 'before', 'after', 'during', 'because', 'led to', 'resulted in'",
    )


class CausalExtractionResult(BaseModel):
    """Structured result from causal extraction."""

    claims: List[CausalClaimModel] = Field(
        default_factory=list,
        description="All causal relationships found in the text",
    )


class CausalExtractionSignature(dspy.Signature):
    """You are a causal reasoning analyst. Extract all causal relationships
    from the text — explicit and strongly implied.

    A causal claim asserts that one event, action, or state CAUSES, LEADS TO,
    RESULTS IN, or ENABLES another.

    Guidelines:
    - Extract EXPLICIT causation: "X caused Y", "because of X, Y happened", "X led to Y"
    - Extract STRONGLY IMPLIED causation: temporal sequences with clear causal links
    - Do NOT extract mere correlations or co-occurrences
    - Do NOT extract temporal sequences without causal implication
    - cause and effect must be specific events, actions, or states — not vague concepts
    - mechanism should explain HOW the cause produces the effect
    - Confidence: 1.0 for explicitly stated ("X caused Y"), 0.7-0.9 for strongly implied,
      0.3-0.6 for plausible but speculative

    Examples:
      "The merger between Acme and Beta Corp led to 200 layoffs in the engineering division"
        → cause=merger between Acme and Beta Corp, effect=200 layoffs in engineering,
          mechanism=post-merger restructuring, confidence=0.95

      "After John got promoted to VP, he moved his family to New York"
        → cause=John's promotion to VP, effect=John moved to New York,
          mechanism=new role required relocation, confidence=0.7

      "The server outage was caused by a misconfigured load balancer"
        → cause=misconfigured load balancer, effect=server outage,
          mechanism=traffic not distributed correctly, confidence=1.0
    """

    schema_reference: str = dspy.InputField(
        desc="Schema.org class reference for typing cause/effect entities"
    )

    source_text: str = dspy.InputField(desc="The text to extract causal relationships from")

    result: CausalExtractionResult = dspy.OutputField(
        desc="All causal claims expressed as structured assertions"
    )
