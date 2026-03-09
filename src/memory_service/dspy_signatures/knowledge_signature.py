"""
DSPy Signatures for Knowledge Operations

1. TaskReinterpretationSignature — pre-mission: reinterpret user prompt,
   extract semantic labels for knowledge graph retrieval.
2. KnowledgeExtractionSignature — post-mission: extract structured knowledge
   entries from completed mission data.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

import dspy


# =========================================================================
# Pydantic Output Models
# =========================================================================

class KnowledgeEntryModel(BaseModel):
    """A single extracted knowledge entry."""
    content: str = Field(
        description="The knowledge statement: specific, actionable, 1-3 sentences. "
                    "Include concrete details (numbers, names, dates, methods, URLs) — "
                    "not vague summaries."
    )
    knowledge_type: str = Field(
        description="One of: "
                    "'fact' (concrete finding or personal detail), "
                    "'pattern' (recurring strategy or behavior), "
                    "'tool_insight' (tool effectiveness/usage), "
                    "'experience' (lesson learned), "
                    "'conclusion' (high-level takeaway), "
                    "'preference' (stated like/dislike, e.g. 'prefers dark mode'), "
                    "'relationship' (connection between people, e.g. 'X is Y\\'s sister'), "
                    "'event' (something that happened/will happen at a specific time), "
                    "'identity' (who someone is, their role, characteristics), "
                    "'temporal_fact' (time-bound or recurring fact, e.g. 'yoga every Tuesday')"
    )
    labels: List[str] = Field(
        description="5-15 semantic labels for retrieval. Lowercase, hyphenated. "
                    "Include: domain terms ('itin-processing'), tool names ('web-search'), "
                    "entity names ('caroline', 'dr-smith'), "
                    "methodologies ('parallel-research'), topics ('tax-filing'), "
                    "temporal markers ('weekly', 'summer-2023'). "
                    "Be specific: 'python-asyncio' not 'programming'. "
                    "More labels means better retrieval — be generous."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this knowledge: 0.0 (speculative) to 1.0 (verified fact). "
                    "Lower for inferences, higher for directly stated information."
    )
    event_date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date (YYYY-MM-DD) when the fact/event occurred or will occur, "
                    "if a specific date is mentioned or can be inferred. "
                    "Examples: '2023-05-07' for 'May 7, 2023'. "
                    "Resolve relative dates ('yesterday', 'last year') using context dates. "
                    "Use null if no specific date is associated."
    )
    reasoning: str = Field(
        description="Brief explanation of why this knowledge is valuable and how it was "
                    "derived from the source data. 1-2 sentences."
    )


class KnowledgeExtractionResult(BaseModel):
    """Structured result from knowledge extraction."""
    entries: List[KnowledgeEntryModel] = Field(
        description="Extracted knowledge entries. Extract ALL valuable knowledge — "
                    "err on the side of more entries rather than fewer. "
                    "Typical range: 5-15 entries depending on mission complexity."
    )


# =========================================================================
# DSPy Signature
# =========================================================================

class KnowledgeExtractionSignature(dspy.Signature):
    """You are a knowledge extraction specialist. Your job is to mine source data
    for every piece of reusable knowledge — facts discovered, patterns observed,
    tool insights gained, lessons learned, personal preferences, relationships,
    events, and identity information.

    Be EXHAUSTIVE and DETAILED. Extract every piece of knowledge that could be useful
    in future interactions. Each entry should be self-contained and specific enough
    to be useful without additional context.

    Knowledge types:
    - fact: Concrete, verifiable findings ("ITIN processing via mail takes 7-11 weeks")
    - pattern: Recurring strategies or behaviors ("User always asks for summaries first")
    - tool_insight: Tool effectiveness, limitations, best practices
    - experience: Lessons learned from execution
    - conclusion: High-level synthesized takeaways
    - preference: Stated like/dislike ("prefers dark mode", "vegetarian")
    - relationship: Connection between people ("Caroline is Julia's daughter")
    - event: Something that happened/will happen ("Caroline went to LGBTQ group on May 7, 2023")
    - identity: Who someone is ("Dr. Smith is a cardiologist at Mayo Clinic")
    - temporal_fact: Time-bound or recurring facts ("yoga class every Tuesday at 6pm")

    Temporal extraction:
    - When a knowledge entry references a SPECIFIC date, extract it as event_date (YYYY-MM-DD)
    - Resolve relative dates ("yesterday", "last year") using the context date if available
    - Recurring events ("every Tuesday") should NOT get an event_date — use temporal_fact type

    Label guidelines:
    - Use specific domain terms: "itin-processing" not "taxes"
    - Include entity names: "caroline", "dr-smith", "mayo-clinic"
    - Include tool names when relevant: "web-search", "scholar-search"
    - Include methodology labels: "parallel-research", "sequential-workflow"
    - Include topic labels: "pricing", "comparison", "how-to", "health"
    - Include temporal markers when relevant: "weekly", "summer-2023", "deadline"
    - Each label should be a single concept, lowercase, hyphenated
    - Aim for 5-15 labels per entry — more labels means better retrieval
    """

    data_source_type: str = dspy.InputField(
        desc="Type of source data: 'mission' (agent task execution with tool calls, "
             "plans, and execution trace) or 'conversation' (dialogue between people). "
             "Adjusts extraction focus accordingly."
    )
    mission_task: str = dspy.InputField(
        desc="The original task/question or conversation topic"
    )
    mission_outcome: str = dspy.InputField(
        desc="Outcome summary: mission status + iterations, or conversation summary"
    )
    full_report: str = dspy.InputField(
        desc="The complete output/report or full conversation text"
    )
    execution_trace: str = dspy.InputField(
        desc="Execution trace (tool calls, reasoning steps) or conversation context"
    )
    plan_execution: str = dspy.InputField(
        desc="Plan with step statuses, or 'N/A' for conversations"
    )
    reflection: str = dspy.InputField(
        desc="Post-completion reflection or summary analysis"
    )

    extraction: KnowledgeExtractionResult = dspy.OutputField(
        desc="Exhaustive list of extracted knowledge entries with semantic labels "
             "and optional event_date for temporally-anchored knowledge"
    )


# =========================================================================
# Task Reinterpretation (pre-mission knowledge retrieval)
# =========================================================================

class TaskReinterpretationResult(BaseModel):
    """Structured reinterpretation of a user's task for knowledge retrieval."""
    reinterpreted_task: str = Field(
        description="Expanded, unambiguous restatement of what the user is asking for. "
                    "Resolve implicit references, fill in context, make the intent explicit. "
                    "2-4 sentences."
    )
    search_query: str = Field(
        description="Optimized search query for vector similarity search against "
                    "a knowledge graph. Should capture the core semantic meaning. "
                    "1-2 sentences, keyword-rich."
    )
    search_labels: List[str] = Field(
        description="10-25 semantic labels for knowledge graph retrieval. Lowercase, "
                    "hyphenated. Cast a WIDE net — include:\n"
                    "- Direct topic labels: the specific subject matter\n"
                    "- Related domain labels: adjacent or parent topics\n"
                    "- Methodology labels: likely approaches (web-search, comparison, etc.)\n"
                    "- Tool labels: tools that might be useful (web-search, fetch-url, etc.)\n"
                    "- Task-type labels: what kind of task this is (research, how-to, fact-check)\n"
                    "- Broader category labels: the field or discipline\n"
                    "Examples: 'france', 'geography', 'capital-cities', 'europe', "
                    "'country-facts', 'web-search', 'factual-query', 'quick-lookup'"
    )
    complexity_assessment: str = Field(
        description="Brief assessment of task complexity: 'trivial' (direct recall), "
                    "'simple' (1-2 tool calls), 'moderate' (multi-step research), "
                    "'complex' (multi-agent delegation). One word."
    )


class TaskReinterpretationSignature(dspy.Signature):
    """You are a task analysis specialist. Your job is to deeply understand a user's request
    and prepare it for knowledge retrieval from a persistent knowledge graph.

    Your goals:
    1. REINTERPRET the task: What is the user really asking? What implicit context exists?
       What would a thorough answer require?
    2. GENERATE SEARCH LABELS: Create a comprehensive set of semantic labels that could
       match relevant prior knowledge. Be GENEROUS — it's better to over-retrieve than miss
       relevant knowledge.
    3. OPTIMIZE SEARCH QUERY: Create a keyword-rich query that captures the semantic
       essence of the task for vector similarity search.
    4. ASSESS COMPLEXITY: How complex is this task? This helps calibrate the approach.

    Label format: lowercase, hyphenated, specific but not overly narrow.
    Good: "python-web-scraping", "api-rate-limiting", "parallel-research"
    Bad: "programming" (too broad), "python-3.12-asyncio-web-scraping-with-aiohttp" (too specific)
    """

    user_task: str = dspy.InputField(
        desc="The raw task/question from the user, exactly as provided"
    )

    analysis: TaskReinterpretationResult = dspy.OutputField(
        desc="Structured task analysis with reinterpretation, search labels, "
             "optimized query, and complexity assessment"
    )
