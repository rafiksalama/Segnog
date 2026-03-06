"""
Artifact Extraction — DSPy-powered post-mission artifact detection.

Scans execution traces for tangible outputs: files saved, content downloaded,
reports generated, datasets compiled, code written.
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.artifact_signature import ArtifactExtractionSignature

logger = logging.getLogger(__name__)


async def extract_artifacts(
    mission_data: Dict[str, Any],
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extract artifact entries from a completed mission using DSPy.

    Args:
        mission_data: Dict with task, status, output, state, iterations, plan, context.
        model: Flash model identifier.

    Returns:
        List of artifact entry dicts with name, artifact_type, path, description, labels.
    """
    task = mission_data.get("task", "")
    status = mission_data.get("status", "")
    iterations = mission_data.get("iterations", 0)
    full_output = mission_data.get("output", "")
    state = mission_data.get("state", {})

    mission_outcome = f"Status: {status} | Iterations: {iterations}"

    # Build execution trace
    execution_context = mission_data.get("context", "")
    state_outputs = state.get("outputs", []) if isinstance(state, dict) else []
    state_progression_parts = []
    for entry in state_outputs:
        it = entry.get("iteration", "?")
        output_text = str(entry.get("output", ""))
        if output_text:
            state_progression_parts.append(f"--- Iteration {it} ---\n{output_text}")

    state_progression = "\n\n".join(state_progression_parts)

    trace_parts = []
    if execution_context:
        trace_parts.append("## Execution Context (Tool Calls & Results)\n" + execution_context)
    if state_progression:
        trace_parts.append("## Agent Reasoning Per Iteration\n" + state_progression)

    state_desc = state.get("state_description", "") if isinstance(state, dict) else ""
    if state_desc:
        trace_parts.append(f"## Final State\n{state_desc}")

    execution_trace = "\n\n".join(trace_parts) or "No execution trace available."

    MAX_TRACE = 20000
    if len(execution_trace) > MAX_TRACE:
        keep_start = 5000
        keep_end = MAX_TRACE - keep_start - 50
        execution_trace = (
            execution_trace[:keep_start]
            + "\n\n... [middle truncated] ...\n\n"
            + execution_trace[-keep_end:]
        )

    # Build plan execution
    plan_data = mission_data.get("plan")
    plan_execution = "No plan created."
    if plan_data and isinstance(plan_data, dict):
        items = plan_data.get("items", [])
        plan_lines = [f"Goal: {plan_data.get('goal', 'N/A')}"]
        for item in items:
            s = item.get("status", "pending")
            icon = {
                "completed": "+", "in_progress": ">",
                "blocked": "!", "skipped": "-",
            }.get(s, " ")
            desc = item.get("description", "")
            plan_lines.append(f"  [{icon}] {desc}")
        plan_execution = "\n".join(plan_lines)

    full_report = full_output or "No output produced."
    MAX_REPORT = 10000
    if len(full_report) > MAX_REPORT:
        full_report = full_report[:MAX_REPORT] + "\n\n... [truncated]"

    try:
        lm = configure_dspy_lm(model=model, temperature=0.2, max_tokens=4096)
        predictor = dspy.Predict(ArtifactExtractionSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(
                mission_task=task,
                mission_outcome=mission_outcome,
                execution_trace=execution_trace,
                plan_execution=plan_execution,
                full_report=full_report,
            )

        extraction = result.extraction
        valid = []
        for entry in extraction.entries:
            valid.append({
                "name": str(entry.name)[:200],
                "artifact_type": entry.artifact_type,
                "path": str(entry.path)[:500],
                "description": str(entry.description)[:500],
                "labels": list(entry.labels)[:7],
            })

        logger.info(f"Extracted {len(valid)} artifact entries via DSPy")
        return valid

    except Exception as e:
        logger.error(f"Artifact extraction failed: {e}")
        return []
