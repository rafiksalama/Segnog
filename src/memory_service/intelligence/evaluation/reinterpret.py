"""
Task Reinterpretation — DSPy-powered pre-mission analysis.

Extracts semantic labels, optimized search query, and complexity assessment
from a raw user task. Used before knowledge/memory retrieval.
"""

import logging
from typing import Any, Dict, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..signatures.knowledge_signature import TaskReinterpretationSignature

logger = logging.getLogger(__name__)


async def reinterpret_task(
    task: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reinterpret a user's task into semantic labels, search query, and complexity.

    Args:
        task: Raw user task/question.
        model: Model identifier (defaults to flash model from config).

    Returns:
        Dict with reinterpreted_task, search_query, search_labels, complexity_assessment.
    """
    try:
        lm = configure_dspy_lm(
            model=model,
            temperature=0.3,
            max_tokens=2048,
        )
        predictor = dspy.Predict(TaskReinterpretationSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = await predictor.acall(user_task=task)

        analysis = result.analysis

        output = {
            "reinterpreted_task": str(analysis.reinterpreted_task),
            "search_query": str(analysis.search_query),
            "search_labels": list(analysis.search_labels)[:25],
            "complexity_assessment": str(analysis.complexity_assessment),
        }

        logger.info(
            f"Task reinterpretation: {len(output['search_labels'])} labels, "
            f"complexity={output['complexity_assessment']}"
        )
        return output

    except Exception as e:
        logger.error(f"Task reinterpretation failed: {e}")
        return {
            "reinterpreted_task": task,
            "search_query": task,
            "search_labels": [],
            "complexity_assessment": "moderate",
        }
