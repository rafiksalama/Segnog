"""
Causal Claim Extraction — LLM-powered causal mining from text.

Extracts causal assertions: "X caused Y because Z". Each claim
identifies cause/effect with a mechanism explanation.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ..llm.client import llm_call

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a causal reasoning analyst. Extract all causal relationships from text.

A causal claim asserts that one event/action/state CAUSES, LEADS TO, or RESULTS IN another.

Rules:
- Extract EXPLICIT causation ("X caused Y", "because of X, Y happened")
- Extract STRONGLY IMPLIED causation (clear causal sequences)
- Do NOT extract mere correlations or temporal co-occurrences
- cause and effect must be specific (not vague concepts)
- Confidence should reflect certainty of the CAUSAL LINK, not just whether it's stated:
  0.9-0.95: direct causation with clear mechanism ("X caused Y because Z")
  0.7-0.85: strong causal link but mechanism unclear or indirect
  0.5-0.65: plausible causation, could be correlation
  0.3-0.45: speculative, weak evidence of causation
  Never use 1.0 — no causal claim is absolutely certain

Return a JSON array of objects with these fields:
  cause, effect, mechanism (optional), confidence (0-1)

Example output:
[
  {"cause": "merger between Acme and Beta", "effect": "200 layoffs in engineering", "mechanism": "post-merger restructuring", "confidence": 0.95},
  {"cause": "layoffs", "effect": "John relocated to NYC", "mechanism": "needed new employment", "confidence": 0.7}
]

Return ONLY the JSON array. No explanation, no markdown."""


async def extract_causal_claims(
    content: str,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract causal claims from text.

    Returns list of dicts with: cause, cause_norm, effect, effect_norm,
    mechanism, confidence.
    """
    if not content or len(content.strip()) < 20:
        return []

    MAX_INPUT = 16000
    if len(content) > MAX_INPUT:
        content = content[:MAX_INPUT]

    try:
        raw = await llm_call(
            f"Extract all causal relationships from this text:\n\n{content}",
            model=model,
            temperature=0.1,
            max_tokens=4000,
            system_prompt=_SYSTEM_PROMPT,
        )

        # Parse JSON from response (handle markdown code blocks, empty responses)
        raw = raw.strip()
        if not raw:
            return []
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not raw or raw[0] not in "[{":
            # Not JSON — LLM returned plain text or empty
            return []

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            parsed = parsed.get("claims", []) if isinstance(parsed, dict) else []

        from ...ontology.names import normalize_name

        claims = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            cause = str(item.get("cause", "")).strip()
            effect = str(item.get("effect", "")).strip()
            if not cause or not effect:
                continue

            cause_norm = normalize_name(cause)
            effect_norm = normalize_name(effect)
            if not cause_norm or not effect_norm:
                continue

            confidence = float(item.get("confidence", 0.8))
            confidence = max(0.0, min(1.0, confidence))

            claims.append(
                {
                    "cause": cause,
                    "cause_norm": cause_norm,
                    "cause_type": "Thing",
                    "effect": effect,
                    "effect_norm": effect_norm,
                    "effect_type": "Thing",
                    "mechanism": str(item.get("mechanism", "")).strip(),
                    "confidence": confidence,
                    "temporal_marker": "",
                }
            )

        logger.info("Extracted %d causal claims", len(claims))
        return claims

    except json.JSONDecodeError as e:
        logger.warning("Causal extraction JSON parse failed: %s", e)
        return []
    except Exception as e:
        logger.error("Causal claim extraction failed: %s", e)
        return []
