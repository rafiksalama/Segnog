"""
Memory Result Filter — Stage 2 of two-stage retrieval.

Takes raw vector search results and the current task, asks the LLM to
score each result for relevance and return only the useful ones.
"""

import logging
from typing import Optional

from ..llm.client import llm_call

logger = logging.getLogger(__name__)


async def filter_memory_results(
    task: str,
    search_results: str,
    model: Optional[str] = None,
    max_results: int = 5,
) -> str:
    """
    LLM-powered relevance filter for memory search results.

    Args:
        task: The current mission/task.
        search_results: Formatted string of vector search results from stage 1.
        model: Model to use (flash/cheap model).
        max_results: Maximum results to return.

    Returns:
        Filtered memory context string for prompt injection.
    """
    prompt = f"""You are a strict relevance filter. Evaluate each retrieved memory against the current task.

## Current Task
{task}

## Retrieved Memories
{search_results}

## Filtering Rules
- RELEVANT: Memory describes the same domain, same type of problem, or a directly transferable technique
- IRRELEVANT: Memory is about a different domain/topic, even if it shares generic keywords like "search", "research", "AI", "analysis"
- When in doubt, REJECT — false negatives are much cheaper than false positives polluting the context

Return ONLY memories that pass the relevance bar (up to {max_results}).

Format:
## Relevant Past Experience
1. [memory summary] — Why: [specific connection to current task]

If nothing is truly relevant, return exactly: "No relevant past experience found."
"""

    try:
        result = await llm_call(prompt, model=model, temperature=0.1, max_tokens=4096)
        logger.info(f"Memory filter returned {len(result)} chars")
        return result
    except Exception as e:
        logger.error(f"Memory filter failed: {e}")
        return ""
