"""
State Inference — LLM-powered state description from task + memories.

Produces a one-sentence state description that becomes the retrieval key
for tool counters, the initial state_description, and is stored with events.
"""

import logging
from typing import Optional

from ..llm.client import llm_call

logger = logging.getLogger(__name__)


async def infer_state(
    task: str,
    retrieved_memories: str,
    model: Optional[str] = None,
) -> str:
    """
    Infer the current agent state from the goal and retrieved context.

    Args:
        task: The current mission/task.
        retrieved_memories: Filtered memories from two-stage retrieval.
        model: Model to use (flash/cheap model).

    Returns:
        One-sentence state description.
    """
    prompt = f"""Based on this goal and any relevant past experience, describe the current situation in one sentence.

Goal: {task}

Past experience:
{retrieved_memories if retrieved_memories else "No relevant past experience."}

Describe the current state in one sentence (what kind of task this is, what domain, what approach is needed):"""

    try:
        result = await llm_call(prompt, model=model, temperature=0.1, max_tokens=256)
        state = result.strip().split("\n")[0].strip()
        logger.info(f"Inferred state: {state[:80]}...")
        return state
    except Exception as e:
        logger.error(f"State inference failed: {e}")
        return ""
