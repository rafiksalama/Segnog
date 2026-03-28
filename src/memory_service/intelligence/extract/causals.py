"""
Causal Claim Extraction — DSPy-powered causal mining from text.

Extracts causal assertions: "X caused Y because Z". Each claim
identifies cause/effect with Schema.org typing and a mechanism.
"""

import logging
from typing import Any, Dict, List, Optional

import dspy

from ..llm.dspy_adapter import configure_dspy_lm, adapter
from ..signatures.causal_signature import CausalExtractionSignature

logger = logging.getLogger(__name__)


def _get_ontology():
    from ...ontology.schema_org import get_shared_ontology
    return get_shared_ontology()


async def extract_causal_claims(
    content: str,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extract causal claims from text using DSPy + Schema.org reference.

    Returns list of dicts with:
      - cause, cause_norm, cause_type
      - effect, effect_norm, effect_type
      - mechanism, confidence, temporal_marker
    """
    if not content or len(content.strip()) < 20:
        return []

    MAX_INPUT = 16000
    if len(content) > MAX_INPUT:
        content = content[:MAX_INPUT]

    onto = _get_ontology()

    try:
        lm = configure_dspy_lm(model=model, temperature=0.1)
        predictor = dspy.Predict(CausalExtractionSignature)

        with dspy.context(lm=lm, adapter=adapter):
            result = await predictor.acall(
                schema_reference=onto.prompt_reference,
                source_text=content,
            )

        extraction = result.result
        claims = []

        from ...ontology.names import normalize_name

        for claim in extraction.claims:
            try:
                if not claim.cause or not claim.effect:
                    continue

                cause = str(claim.cause).strip()
                effect = str(claim.effect).strip()
                if not cause or not effect:
                    continue

                cause_type = onto.normalize_class(str(claim.cause_type or "Thing"))
                effect_type = onto.normalize_class(str(claim.effect_type or "Thing"))

                cause_norm = normalize_name(cause)
                effect_norm = normalize_name(effect)
                if not cause_norm or not effect_norm:
                    continue

                confidence = float(claim.confidence) if claim.confidence is not None else 0.8
                confidence = max(0.0, min(1.0, confidence))

                claims.append({
                    "cause": cause,
                    "cause_norm": cause_norm,
                    "cause_type": cause_type,
                    "effect": effect,
                    "effect_norm": effect_norm,
                    "effect_type": effect_type,
                    "mechanism": str(claim.mechanism or "").strip(),
                    "confidence": confidence,
                    "temporal_marker": str(claim.temporal_marker or "").strip(),
                })
            except Exception as item_err:
                logger.debug("Skipping malformed causal claim: %s", item_err)

        logger.info("Extracted %d causal claims via DSPy", len(claims))
        return claims

    except Exception as e:
        logger.error("Causal claim extraction failed: %s", e)
        return []
