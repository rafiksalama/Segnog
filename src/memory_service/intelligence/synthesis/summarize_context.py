"""Session context summarization — DSPy-powered synthesis of session context
relevant to the current observation."""

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..signatures.context_signature import ContextSummarizationSignature

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "local": "Observation",
    "hydrated": "Related Memory",
    "hydrated_knowledge": "Knowledge",
    "ontology_node": "Entity Profile",
    "relevant_episode": "Related Memory",
    "reflection": "Reflection",
    "metacognition": "Metacognition",
    "causal_reflection": "Causal Reflection",
    "causal_claim": "Causal Belief",
}

# Default rank for source types without a 3D score.
# Higher = shown first.  Entity profiles and knowledge are stable facts
# so they get a baseline above zero; observations/episodes rely on their
# computed rank from semantic + temporal + Hebbian scoring.
_DEFAULT_RANK = {
    "ontology_node": 0.85,
    "hydrated_knowledge": 0.75,
    "causal_claim": 0.80,
    "reflection": 0.70,
    "local": 0.50,
    "hydrated": 0.0,  # should have a real rank from 3D scoring
    "relevant_episode": 0.0,
}


def _format_entries(entries: Dict[str, Any]) -> str:
    """Format session entries ranked by 3D score (semantic + temporal + Hebbian).

    Each entry may carry a ``rank`` field set by the observe pipeline.
    Entries without an explicit rank use a source-type default.
    Output is ordered highest-rank first, grouped by source type within
    equal-rank tiers.
    """
    now = time.time()
    items = []
    for uuid, entry in entries.items():
        source_type = entry.get("source_type", "local")
        # rank = 3D composite score when available, else source-type default
        rank = entry.get("rank", entry.get("score", _DEFAULT_RANK.get(source_type, 0.0)))
        items.append(
            {
                "content": entry.get("content", "")[:800],  # Truncate long entries for context
                "source_type": source_type,
                "created_at": entry.get("created_at", 0),
                "event_date": entry.get("event_date", ""),
                "rank": rank,
            }
        )

    # Primary: rank descending. Secondary: created_at ascending (older first within same rank).
    items.sort(key=lambda x: (-x["rank"], x["created_at"]))

    lines = []
    for i, item in enumerate(items, 1):
        label = _SOURCE_LABELS.get(item["source_type"], item["source_type"])
        ts = ""
        age = ""
        if item["created_at"] > 0:
            dt = datetime.fromtimestamp(item["created_at"])
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            elapsed = int(now - item["created_at"])
            if elapsed < 0:
                elapsed = 0
            h, remainder = divmod(elapsed, 3600)
            m, s = divmod(remainder, 60)
            age = f"{h}:{m:02d}:{s:02d} ago"
        elif item.get("event_date"):
            ts = item["event_date"]
        content_prefix = f"[{ts} | {age}] " if ts and age else f"[{ts}] " if ts else ""
        rank_str = f" (rank:{item['rank']:.2f})" if item["rank"] > 0 else ""
        lines.append(f"{i}. [{label}]{rank_str} {content_prefix}{item['content']}")

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
            model=model,
            temperature=0.2,
            max_tokens=196000,
        )
        predictor = dspy.Predict(ContextSummarizationSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = await predictor.acall(
                current_observation=current_observation,
                session_context=formatted,
            )

        summary = str(result.result.summary).strip()
        logger.info(f"Context summary: {len(summary)} chars from {len(session_entries)} entries")
        return summary
    except Exception as e:
        logger.error(f"Context summarization failed: {e}")
        return ""
