"""Session context summarization — DSPy-powered synthesis of session context
relevant to the current observation."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.context_signature import ContextSummarizationSignature

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "local": "Observation",
    "hydrated": "Related Memory",
    "hydrated_knowledge": "Knowledge",
    "ontology_node": "Entity Profile",
    "relevant_episode": "Related Memory",
}


def _format_entries(entries: Dict[str, Any]) -> str:
    """Format session entries as numbered text for the LLM prompt."""
    items = []
    for uuid, entry in entries.items():
        items.append({
            "content": entry.get("content", ""),
            "source_type": entry.get("source_type", "local"),
            "created_at": entry.get("created_at", 0),
        })

    items.sort(key=lambda x: x["created_at"])

    lines = []
    for i, item in enumerate(items, 1):
        label = _SOURCE_LABELS.get(item["source_type"], item["source_type"])
        ts = ""
        if item["created_at"] > 0:
            ts = datetime.fromtimestamp(item["created_at"]).strftime("%H:%M:%S")
            ts = f" [{ts}]"
        lines.append(f"{i}. [{label}]{ts} {item['content']}")

    return "\n".join(lines)


async def summarize_context(
    current_observation: str,
    session_entries: Dict[str, Any],
    model: Optional[str] = None,
) -> str:
    """Summarize session context relevant to the current observation.

    Args:
        current_observation: The raw observation text just received.
        session_entries: All session entries from DragonflyDB (session_get_all),
                         mapping uuid -> {content, source_type, created_at, ...}.
        model: Optional model override.

    Returns:
        Concise text summary of relevant context, or empty string on error.
    """
    if not session_entries:
        return ""

    formatted = _format_entries(session_entries)

    try:
        lm = configure_dspy_lm(
            model=model, temperature=0.2, max_tokens=20000,
        )
        predictor = dspy.Predict(ContextSummarizationSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(
                current_observation=current_observation,
                session_context=formatted,
            )

        summary = str(result.result.summary).strip()
        logger.info(f"Context summary: {len(summary)} chars from {len(session_entries)} entries")
        return summary
    except Exception as e:
        logger.error(f"Context summarization failed: {e}")
        return ""
