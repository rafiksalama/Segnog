"""
Knowledge Extraction — DSPy-powered post-mission knowledge mining.

Extracts structured knowledge entries (facts, patterns, insights)
from completed mission data.
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..signatures.knowledge_signature import KnowledgeExtractionSignature

logger = logging.getLogger(__name__)


async def extract_knowledge(
    mission_data: Dict[str, Any],
    reflection: str,
    model: Optional[str] = None,
    data_source_type: str = "mission",
) -> List[Dict[str, Any]]:
    """
    Extract structured knowledge entries from a completed mission using DSPy.

    Args:
        mission_data: Dict with task, status, output, state, iterations, plan, context.
        reflection: Generated reflection text.
        model: Flash model identifier.
        data_source_type: "mission" or "conversation" — adjusts extraction focus.

    Returns:
        List of knowledge entry dicts with content, knowledge_type, labels, confidence, event_date.
    """
    task = mission_data.get("task", "")
    status = mission_data.get("status", "")
    full_output = mission_data.get("output", "")
    state = mission_data.get("state", {})
    iterations = mission_data.get("iterations", 0)

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

    # Cap to avoid token overflow
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
                "completed": "+",
                "in_progress": ">",
                "blocked": "!",
                "skipped": "-",
            }.get(s, " ")
            desc = item.get("description", "")
            plan_lines.append(f"  [{icon}] {desc}")
        plan_execution = "\n".join(plan_lines)

    full_report = full_output or "No output produced."
    MAX_REPORT = 10000
    if len(full_report) > MAX_REPORT:
        full_report = full_report[:MAX_REPORT] + "\n\n... [truncated]"

    reflection_text = reflection or "No reflection available."

    def _validate_entries(raw_entries: list) -> list:
        """Validate and normalise a list of raw entry dicts."""
        from datetime import date as _date

        valid = []
        for entry in raw_entries:
            validated_date = None
            ev = (
                entry.get("event_date")
                if isinstance(entry, dict)
                else getattr(entry, "event_date", None)
            )
            if ev:
                try:
                    _date.fromisoformat(str(ev))
                    validated_date = str(ev)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid event_date '{ev}', discarding")

            if isinstance(entry, dict):
                content = entry.get("content", "")
                ktype = entry.get("knowledge_type", "fact")
                labels = entry.get("labels", [])
                confidence = entry.get("confidence", 0.8)
            else:
                content = getattr(entry, "content", "")
                ktype = getattr(entry, "knowledge_type", "fact")
                labels = getattr(entry, "labels", [])
                confidence = getattr(entry, "confidence", 0.8)

            valid.append(
                {
                    "content": str(content)[:500],
                    "knowledge_type": ktype,
                    "labels": list(labels)[:15],
                    "confidence": min(1.0, max(0.0, float(confidence))),
                    "event_date": validated_date,
                }
            )
        return valid

    try:
        lm = configure_dspy_lm(model=model, temperature=0.3)
        predictor = dspy.Predict(KnowledgeExtractionSignature)

        try:
            with dspy.context(lm=lm, adapter=adapter):
                result = await predictor.acall(
                    data_source_type=data_source_type,
                    mission_task=task,
                    mission_outcome=mission_outcome,
                    full_report=full_report,
                    execution_trace=execution_trace,
                    plan_execution=plan_execution,
                    reflection=reflection_text,
                )
            raw_entries = result.extraction.entries
        except Exception as parse_err:
            # DSPy's JSONAdapter may fail when the LM returns {"entries": [...]}
            # instead of {"extraction": {"entries": [...]}}. Fall back to lm.history.
            logger.warning(f"DSPy parse failed ({parse_err}), trying raw LM history fallback")
            import json

            raw_entries = []
            try:
                history = lm.history or []
                if history:
                    last = history[-1]
                    outputs = last.get("outputs") or last.get("completions") or []
                    for out in outputs:
                        text = out if isinstance(out, str) else out.get("text", "")
                        parsed = json.loads(text)
                        # Handle {"entries": [...]} or {"extraction": {"entries": [...]}}
                        if "entries" in parsed:
                            raw_entries = parsed["entries"]
                        elif "extraction" in parsed:
                            raw_entries = parsed["extraction"].get("entries", [])
                        if raw_entries:
                            break
            except Exception as fb_err:
                logger.error(f"Raw LM fallback also failed: {fb_err}")

        valid = _validate_entries(raw_entries)
        logger.info(f"Extracted {len(valid)} knowledge entries via DSPy")
        return valid

    except Exception as e:
        logger.error(f"Knowledge extraction failed: {e}")
        return []
