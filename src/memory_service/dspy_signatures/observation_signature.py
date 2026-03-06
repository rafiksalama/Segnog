"""
DSPy Signature for Observation Judging

Analyzes an observation from an AI agent and decides:
- observation_type: what kind of observation this is
- storage_tier: where to store it (short_term, long_term, both)
- search_query: optimized query for retrieval
- search_labels: semantic labels for knowledge hybrid search
- importance: how much retrieval depth to apply
"""

from typing import List
from pydantic import BaseModel, Field

import dspy


class ObservationAnalysis(BaseModel):
    """Routing analysis for an observation."""
    observation_type: str = Field(
        description="One of: 'chat' (conversation turn, user message, agent response), "
                    "'tool_call' (tool invocation — API call, search, file op), "
                    "'tool_result' (output/response from a tool call), "
                    "'knowledge' (learned fact, discovered information, user preference), "
                    "'artifact' (created or found resource — file, report, dataset, URL), "
                    "'action' (agent decision or action taken), "
                    "'error' (failure, exception, blocked operation), "
                    "'state_update' (status change, progress update)"
    )
    storage_tier: str = Field(
        description="Where to store this observation: "
                    "'short_term' — ephemeral event only, for routine noise "
                    "(heartbeats, HTTP 200s, trivial acknowledgments). "
                    "'long_term' — embedded episode for later retrieval, for high-value "
                    "observations (insights, preferences, important results). "
                    "'both' — event stream AND embedded episode, for important observations "
                    "that also need event-stream context (most observations land here)."
    )
    search_query: str = Field(
        description="Optimized 1-2 sentence query for vector similarity retrieval. "
                    "Keyword-rich, captures the semantic core of the observation."
    )
    search_labels: List[str] = Field(
        description="5-15 semantic labels for knowledge graph retrieval. Lowercase, "
                    "hyphenated. Include: domain terms, tool names, entity names, "
                    "topics, methodologies. Be specific: 'weather-api' not 'api'."
    )
    importance: str = Field(
        description="One of: 'low' (routine operation, acknowledgment, status ping), "
                    "'medium' (useful context, standard tool result, conversation flow), "
                    "'high' (key discovery, user preference, critical error, decision)"
    )


class ObservationJudgeSignature(dspy.Signature):
    """You are a memory routing specialist. Analyze an observation from an AI agent
    and decide how it should be stored and what context should be retrieved.

    Observation types:
    - chat: Conversation turns, user messages, agent responses
    - tool_call: Tool invocations (API calls, searches, file operations)
    - tool_result: Output/response from tool calls with actual data
    - knowledge: Learned facts, insights, discovered information, user preferences
    - artifact: Created or found resources (files, reports, datasets, URLs)
    - action: Agent decisions or actions taken
    - error: Failures, exceptions, blocked operations
    - state_update: Status changes, progress updates

    Storage routing guidelines:
    - short_term: Routine events not worth embedding — "Called API", "Received 200 OK",
      "Waiting for response", heartbeats. These add to the event stream for compression
      but aren't individually worth retrieving later.
    - long_term: High-value observations worth embedding for future retrieval —
      "User prefers Celsius", "Discovered the API requires OAuth2", key findings.
      Skip the event stream, go straight to episodic memory.
    - both: Important observations that belong in both tiers — substantive tool results,
      meaningful conversation turns, significant actions. Most observations land here.

    Importance guidelines:
    - low: Routine operations, simple acknowledgments, status pings, trivial updates
    - medium: Useful context, standard results, normal conversation flow
    - high: Key discoveries, user preferences, critical errors, important decisions

    Search query: Rewrite the observation into a keyword-rich query optimized for
    vector similarity search. Focus on the semantic core, not the narrative wrapper.

    Search labels: Generate specific, lowercase, hyphenated labels covering the
    domain, tools, entities, and topics mentioned in the observation.
    """

    observation: str = dspy.InputField(
        desc="The observation text from the agent"
    )
    source: str = dspy.InputField(
        desc="Who or what generated this observation (agent name, tool name, or 'unknown')"
    )

    analysis: ObservationAnalysis = dspy.OutputField(
        desc="Routing analysis: observation type, storage tier, search optimization, importance"
    )
