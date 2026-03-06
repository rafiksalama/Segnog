"""
DSPy Signatures for Knowledge Operations

1. TaskReinterpretationSignature — pre-mission: reinterpret user prompt,
   extract semantic labels for knowledge graph retrieval.
2. KnowledgeExtractionSignature — post-mission: extract structured knowledge
   entries from completed mission data.
"""

from typing import List
from pydantic import BaseModel, Field

import dspy


# =========================================================================
# Pydantic Output Models
# =========================================================================

class KnowledgeEntryModel(BaseModel):
    """A single extracted knowledge entry."""
    content: str = Field(
        description="The knowledge statement: specific, actionable, 1-3 sentences. "
                    "Include concrete details (numbers, names, methods, URLs) — "
                    "not vague summaries."
    )
    knowledge_type: str = Field(
        description="One of: 'fact' (concrete finding), 'pattern' (recurring strategy), "
                    "'tool_insight' (tool effectiveness/usage), 'experience' (lesson learned), "
                    "'conclusion' (high-level takeaway)"
    )
    labels: List[str] = Field(
        description="3-7 semantic labels for retrieval. Lowercase, hyphenated. "
                    "Include: domain terms ('itin-processing'), tool names ('web-search'), "
                    "methodologies ('parallel-research'), topics ('tax-filing'). "
                    "Be specific: 'python-asyncio' not 'programming'."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this knowledge: 0.0 (speculative) to 1.0 (verified fact). "
                    "Lower for inferences, higher for directly observed results."
    )
    reasoning: str = Field(
        description="Brief explanation of why this knowledge is valuable and how it was "
                    "derived from the mission data. 1-2 sentences."
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
    """You are a knowledge extraction specialist. Your job is to mine completed mission data
    for every piece of reusable knowledge — facts discovered, patterns observed, tool insights
    gained, lessons learned, and conclusions drawn.

    Be EXHAUSTIVE and DETAILED. Extract every piece of knowledge that could be useful in
    future missions on related topics. Each entry should be self-contained and specific enough
    to be useful without additional context.

    Knowledge types:
    - fact: Concrete, verifiable findings ("ITIN processing via mail takes 7-11 weeks")
    - pattern: Recurring strategies or approaches ("Parallel web searches outperform sequential for multi-faceted research")
    - tool_insight: Tool effectiveness, limitations, or best practices ("web-search fails for academic papers, use scholar-search instead")
    - experience: Lessons learned from execution ("Fetching >3 URLs per iteration doesn't improve quality")
    - conclusion: High-level synthesized takeaways ("Framework X is best for real-time applications")

    Label guidelines:
    - Use specific domain terms: "itin-processing" not "taxes"
    - Include tool names when relevant: "web-search", "scholar-search", "fetch-url"
    - Include methodology labels: "parallel-research", "sequential-workflow", "delegation"
    - Include topic labels: "pricing", "comparison", "how-to", "best-practices"
    - Each label should be a single concept, lowercase, hyphenated
    - Be generous with labels — more labels means better retrieval later
    """

    mission_task: str = dspy.InputField(
        desc="The original task/question the agent was asked to accomplish"
    )
    mission_outcome: str = dspy.InputField(
        desc="Mission status ('success' or 'max_iterations') and iteration count"
    )
    full_report: str = dspy.InputField(
        desc="The agent's complete final output/report"
    )
    execution_trace: str = dspy.InputField(
        desc="Complete execution trace: all tool calls with their full outputs, "
             "agent reasoning at each step, intermediate state descriptions, "
             "and any agent delegations with their results"
    )
    plan_execution: str = dspy.InputField(
        desc="The execution plan with status of each step "
             "(completed/in-progress/blocked/skipped/pending)"
    )
    reflection: str = dspy.InputField(
        desc="Post-mission reflection analyzing what worked, what didn't, "
             "and lessons learned"
    )

    extraction: KnowledgeExtractionResult = dspy.OutputField(
        desc="Exhaustive list of extracted knowledge entries with semantic labels"
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
