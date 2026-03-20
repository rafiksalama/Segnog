"""
Reflection Generation — LLM-powered post-mission reflection.

Generates a structured reflection from completed mission data that becomes
a high-quality retrieval target — denser and more useful than raw traces.
"""

import logging
from typing import Any, Dict, Optional

from ..llm.client import llm_call
from ...config import get_flash_model

logger = logging.getLogger(__name__)


async def generate_reflection(
    mission_data: Dict[str, Any],
    model: Optional[str] = None,
) -> str:
    """
    Generate a structured reflection from a completed mission.

    Args:
        mission_data: Dict with run_id, task, status, output, state, iterations, plan.
        model: Model to use (defaults to flash model).

    Returns:
        Structured reflection text.
    """
    model = model or get_flash_model()

    task = mission_data.get("task", "")[:500]
    status = mission_data.get("status", "")
    output = mission_data.get("output", "")[:2000]
    state = mission_data.get("state", {})
    state_desc = state.get("state_description", "") if isinstance(state, dict) else ""
    iterations = mission_data.get("iterations", 0)
    plan_data = mission_data.get("plan")

    # Format plan progression
    plan_section = ""
    if plan_data and isinstance(plan_data, dict):
        plan_lines = [f"Plan goal: {plan_data.get('goal', 'N/A')[:100]}"]
        for item in plan_data.get("items", []):
            s = item.get("status", "pending")
            desc = item.get("description", "")[:80]
            result = item.get("result", "")
            result_str = f" → {result[:60]}" if result else ""
            plan_lines.append(f"  [{s}] {desc}{result_str}")
        plan_section = "\n## Plan Execution\n" + "\n".join(plan_lines)

    # Format judge history
    judge_section = ""
    judge_round = state.get("judge_eval_round", 0) if isinstance(state, dict) else 0
    judge_feedback = state.get("judge_previous_feedback", "") if isinstance(state, dict) else ""
    if judge_round > 0:
        judge_section = (
            f"\n## Judge Evaluation\nRounds: {judge_round}\nLast feedback: {judge_feedback[:300]}"
        )

    prompt = f"""Review this completed mission and produce a structured reflection.

## Mission
Task: {task}
Outcome: {status}
Iterations used: {iterations}
Final state: {state_desc}
{plan_section}
{judge_section}

## Output produced
{output}

## Instructions
Produce a concise reflection covering:
1. **Summary**: One sentence describing what happened
2. **What worked**: Tools and strategies that were effective
3. **What didn't work**: Failures, dead ends, or inefficiencies
4. **Plan effectiveness**: How well did the plan structure serve the task? Were parallel items used well?
5. **Skills used**: Key tools and their effectiveness
6. **Novel situations**: Anything new or unexpected encountered
7. **Retrieval key**: One sentence that would help find this experience in the future
"""

    try:
        reflection = await llm_call(prompt, model=model, temperature=0.3, max_tokens=4096)
        logger.info(f"Generated reflection: {len(reflection)} chars")
        return reflection
    except Exception as e:
        logger.error(f"Reflection generation failed: {e}")
        return f"Mission completed with status={status}. Reflection generation failed: {e}"
