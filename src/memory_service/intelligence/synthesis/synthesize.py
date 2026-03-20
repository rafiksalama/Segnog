"""
Background Synthesis — LLM-powered narrative generation.

Synthesizes raw memory data (episodes, tool stats, state, knowledge, artifacts)
into a natural-language background briefing paragraph for prompt injection.
"""

import logging
from typing import Optional

from ..llm.client import llm_call

logger = logging.getLogger(__name__)


async def synthesize_background(
    task: str,
    long_term_context: str,
    tool_stats_context: str,
    inferred_state: str,
    model: Optional[str] = None,
    knowledge_context: str = "",
    artifacts_context: str = "",
    episode_store=None,
) -> dict:
    """
    Synthesize raw memory data into a natural-language background briefing.

    Args:
        task: The current mission/task.
        long_term_context: Filtered episode search results.
        tool_stats_context: Formatted tool experience stats.
        inferred_state: One-sentence state description.
        model: Flash model identifier.
        knowledge_context: Accumulated knowledge from hybrid search.
        artifacts_context: Known artifacts from hybrid search.
        episode_store: Optional EpisodeStore for persisting the narrative.

    Returns:
        Dict with "narrative" (str) and "episode_uuid" (str, empty if not stored).
    """
    knowledge_section = ""
    if knowledge_context:
        knowledge_section = f"""
## Accumulated Knowledge (from knowledge graph)
{knowledge_context}
"""

    artifacts_section = ""
    if artifacts_context:
        artifacts_section = f"""
## Known Artifacts (from artifact registry)
{artifacts_context}
"""

    prompt = f"""You are a briefing writer for an AI agent about to start a task.
Synthesize the following raw information into a concise, natural-language briefing.

## Current Task
{task}

## Past Experience (from long-term memory)
{long_term_context or "No relevant past experience found."}

## Tool Experience
{tool_stats_context or "No tool usage history available."}
{knowledge_section}{artifacts_section}
## Current Situation
{inferred_state or "New task, no prior state."}

## Instructions
Write a single paragraph (4-8 sentences) that covers:
1. What relevant past work exists and key findings from it
2. Which tools have been reliable and which to avoid (if tool stats available)
3. Accumulated knowledge: facts, patterns, and insights from prior missions that apply here
4. Known artifacts: files, reports, or datasets from prior missions that are available and relevant
5. What the current situation is and what approach seems appropriate
6. Any lessons or patterns from past experience that apply here

Rules:
- Write in first-person plural ("We have...", "Our experience shows...")
- Be specific: cite tool names, success rates, prior task outcomes when available
- Integrate accumulated knowledge naturally (don't just list it)
- Mention relevant artifacts by name and path so the agent can reference them
- If no past experience exists, say so briefly and focus on the task at hand
- Do NOT list raw data — synthesize it into a narrative
- Keep it under 250 words"""

    narrative = ""
    episode_uuid = ""

    try:
        narrative = await llm_call(prompt, model=model, temperature=0.2, max_tokens=4096)
        narrative = narrative.strip()
        logger.info(f"Background narrative synthesized: {len(narrative)} chars")
    except Exception as e:
        logger.error(f"Background synthesis failed: {e}")
        return {"narrative": "", "episode_uuid": ""}

    # Store as long-term "narrative" episode if store provided
    if narrative and episode_store:
        try:
            episode_uuid = await episode_store.store_episode(
                content=f"Background briefing for task: {task[:200]}\n\n{narrative}",
                metadata={
                    "source": "synthesizer",
                    "task": task[:200],
                    "inferred_state": inferred_state[:200] if inferred_state else "",
                },
                episode_type="narrative",
            )
            logger.debug("Stored narrative episode")
        except Exception as e:
            logger.warning(f"Failed to store narrative episode (non-critical): {e}")

    return {"narrative": narrative, "episode_uuid": episode_uuid}
