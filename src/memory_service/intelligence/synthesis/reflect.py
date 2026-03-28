"""
Reflection & Metacognition — LLM-powered post-mission analysis.

Generates separate, independently searchable sections:
1. Structured reflection — what happened, what worked, what didn't
2. Metacognition — analysis of the reasoning process itself

Each section is returned separately so callers can store them as
distinct episodes with their own episode_type.
"""

import logging
from typing import Any, Dict, List, Optional

from ..llm.client import llm_call, get_reasoning_traces
from ...config import get_flash_model

logger = logging.getLogger(__name__)


async def generate_metacognition(
    task: str,
    reflection: str,
    reasoning_traces: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
) -> str:
    """
    Generate metacognitive analysis of the system's reasoning process.

    Examines *how* the system reasoned — cognitive patterns, assumptions,
    biases, dead-ends, breakthroughs — using the reflection output and
    any captured reasoning traces.
    """
    model = model or get_flash_model()

    # Format reasoning traces if available
    traces_section = ""
    if reasoning_traces:
        trace_lines = []
        for i, t in enumerate(reasoning_traces, 1):
            trace_lines.append(
                f"### Trace {i} ({t['caller']})\n"
                f"Prompt context: {t['prompt_snippet']}\n"
                f"Reasoning:\n{t['reasoning']}\n"
            )
        traces_text = "\n".join(trace_lines)
        if len(traces_text) > 100_000:
            traces_text = traces_text[:100_000] + "\n\n[...truncated...]"
        traces_section = f"\n## Internal Reasoning Traces\n{traces_text}"

    prompt = f"""You are a metacognitive analyst. Analyse HOW the AI system reasoned
about this task — not what it produced, but the quality and patterns of its thinking.

## Task
{task[:500]}

## Reflection (system's self-assessment)
{reflection[:5000]}
{traces_section}

## Instructions
Produce a structured metacognition report covering:

1. **Reasoning Patterns**: What cognitive strategies were used? (decomposition, analogy, elimination, chain-of-thought, etc.)
2. **Assumptions Made**: What did the system assume without verification? Were assumptions valid?
3. **Decision Points**: Key moments where the reasoning branched — what was chosen and why?
4. **Dead Ends & Corrections**: Where did reasoning go wrong? How was it corrected?
5. **Confidence Calibration**: Was the system appropriately confident/uncertain? Any overconfidence?
6. **Information Gaps**: What information was missing that would have helped?
7. **Cognitive Biases**: Any signs of anchoring, confirmation bias, availability bias, etc.?
8. **Reasoning Quality Score**: Rate 1-10 with brief justification.
9. **Improvement Suggestions**: How could the reasoning process be improved next time?

Be concise but specific. Reference actual content from the reflection and traces.
"""

    try:
        metacognition = await llm_call(
            prompt, model=model, temperature=0.3,
            max_tokens=16000, reasoning_effort="high",
        )
        logger.info(
            "Generated metacognition: %d chars (traces: %d)",
            len(metacognition),
            len(reasoning_traces) if reasoning_traces else 0,
        )
        return metacognition
    except Exception as e:
        logger.error("Metacognition generation failed: %s", e)
        return ""


async def generate_reflection(
    mission_data: Dict[str, Any],
    model: Optional[str] = None,
    group_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Generate structured reflection with metacognition from a completed mission.

    Returns a dict with separate sections:
        {
            "reflection": "...",       # structured mission analysis
            "metacognition": "...",    # reasoning quality analysis
        }
    Each section can be stored as its own episode_type.
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

    reflection = ""
    try:
        reflection = await llm_call(
            prompt, model=model, temperature=0.3,
            max_tokens=16000, reasoning_effort="high",
            group_id=group_id, caller="generate_reflection",
        )
        logger.info("Generated reflection: %d chars", len(reflection))
    except Exception as e:
        logger.error("Reflection generation failed: %s", e)
        reflection = f"Mission completed with status={status}. Reflection generation failed: {e}"

    # ── Metacognition: always run, using reflection + any buffered traces ──
    traces = get_reasoning_traces(group_id) if group_id else []
    metacognition = await generate_metacognition(
        task=task,
        reflection=reflection,
        reasoning_traces=traces or None,
        model=model,
    )

    return {
        "reflection": reflection,
        "metacognition": metacognition,
    }
