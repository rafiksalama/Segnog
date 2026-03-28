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
    memories_text = retrieved_memories if retrieved_memories else "No relevant past experience."

    system = "You describe the current state of a task in one concise sentence. Always respond with exactly one sentence."
    prompt = f"Goal: {task}\nPast experience: {memories_text}\nDescribe the current state:"

    for attempt in range(2):
        try:
            result = await llm_call(
                prompt,
                model=model,
                temperature=0.3,
                max_tokens=196000,
                system_prompt=system,
            )
            # Take the first non-empty line
            state = ""
            for line in result.strip().splitlines():
                line = line.strip()
                if line:
                    state = line
                    break
            if state:
                logger.info(f"Inferred state: {state[:80]}...")
                return state
            logger.warning(f"State inference returned empty (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"State inference failed (attempt {attempt + 1}): {e}")

    return ""
