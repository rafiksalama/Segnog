"""Blend PPR + vector + causal-evidence + temporal + Hebbian into a final score."""
from typing import Any, Dict, List


def blend_score(c: Dict[str, Any], w: Dict[str, float]) -> float:
    return (
        w["w_ppr"] * c.get("ppr_mass", 0.0)
        + w["w_vector"] * c.get("vector_score", 0.0)
        + w["w_causal_evidence"] * c.get("causal_evidence", 0.0)
        + w["w_temporal"] * c.get("temporal", 0.0)
        + w["w_hebbian"] * c.get("hebbian", 0.0)
    )


def rerank(candidates: List[Dict[str, Any]], w: Dict[str, float], top_k: int) -> List[Dict[str, Any]]:
    for c in candidates:
        c["score"] = blend_score(c, w)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]
