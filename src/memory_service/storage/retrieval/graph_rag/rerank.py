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
    # Sort by score desc, breaking ties on uuid asc. The deterministic tie-break
    # is essential: candidate input order from graph/vector queries is not stable
    # across runs, so equal-score items would otherwise shuffle between calls.
    candidates.sort(key=lambda x: (-x["score"], x.get("uuid", "")))
    return candidates[:top_k]
