"""
Observation Judge — DSPy-powered observation analysis and routing.

Analyzes an observation and decides: observation type, storage tier,
optimized search query, semantic labels, and importance level.
Used by the observe endpoint to route observations automatically.
"""

import logging
from typing import Any, Dict, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..dspy_signatures.observation_signature import ObservationJudgeSignature

logger = logging.getLogger(__name__)

# Default fallback when the judge fails
_FALLBACK = {
    "observation_type": "chat",
    "storage_tier": "both",
    "search_query": "",
    "search_labels": [],
    "importance": "medium",
}


async def judge_observation(
    content: str,
    source: str = "",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an observation and return routing decisions.

    Args:
        content: The observation text.
        source: Who/what generated this observation.
        model: Model identifier (defaults to flash model from config).

    Returns:
        Dict with observation_type, storage_tier, search_query,
        search_labels, importance.
    """
    try:
        lm = configure_dspy_lm(
            model=model,
            temperature=0.3,
            max_tokens=1024,
        )
        predictor = dspy.Predict(ObservationJudgeSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = predictor(
                observation=content,
                source=source or "unknown",
            )

        analysis = result.analysis

        # Validate observation_type
        valid_types = {
            "chat", "tool_call", "tool_result", "knowledge",
            "artifact", "action", "error", "state_update",
        }
        obs_type = str(analysis.observation_type).lower()
        if obs_type not in valid_types:
            obs_type = "chat"

        # Validate storage_tier
        valid_tiers = {"short_term", "long_term", "both"}
        tier = str(analysis.storage_tier).lower().replace(" ", "_")
        if tier not in valid_tiers:
            tier = "both"

        # Validate importance
        valid_importance = {"low", "medium", "high"}
        importance = str(analysis.importance).lower()
        if importance not in valid_importance:
            importance = "medium"

        output = {
            "observation_type": obs_type,
            "storage_tier": tier,
            "search_query": str(analysis.search_query) or content,
            "search_labels": list(analysis.search_labels)[:15],
            "importance": importance,
        }

        logger.info(
            f"Observation judge: type={output['observation_type']}, "
            f"tier={output['storage_tier']}, importance={output['importance']}, "
            f"{len(output['search_labels'])} labels"
        )
        return output

    except Exception as e:
        logger.error(f"Observation judge failed: {e}")
        fallback = dict(_FALLBACK)
        fallback["search_query"] = content
        return fallback
