"""Scoring utilities for multi-dimension retrieval.

Two-dimension (semantic + temporal):
    final_score = (1 - alpha) * semantic + alpha * freshness

Three-dimension with Hebbian learning (semantic + temporal + co-activation):
    final_score = (1 - alpha - beta) * semantic + alpha * freshness + beta * hebbian

Parameters are store-specific and configurable via settings.toml.
"""

import math
import time
from typing import Any, Dict, List, Optional


def compute_freshness(
    created_at: float,
    half_life_hours: float,
    now: float = None,
) -> float:
    """Hyperbolic freshness: 1/(1 + age_hours/half_life). Returns (0, 1]."""
    now = now or time.time()
    age_hours = max(0.0, (now - created_at) / 3600.0)
    return 1.0 / (1.0 + age_hours / half_life_hours)


def apply_temporal_score(
    results: List[Dict[str, Any]],
    alpha: float,
    half_life_hours: float,
    score_key: str = "score",
    time_key: str = "created_at",
    now: float = None,
) -> List[Dict[str, Any]]:
    """Re-score and re-sort results with temporal blending.

    For each result:
        freshness = compute_freshness(result[time_key], half_life_hours)
        result[score_key] = (1 - alpha) * semantic + alpha * freshness

    Preserves ``_semantic_score`` and ``_freshness`` on each result.
    Returns results sorted by new score descending.
    """
    now = now or time.time()
    for result in results:
        semantic = result.get(score_key, 0.0)
        created_at = result.get(time_key, 0.0)
        if created_at <= 0:
            result["_semantic_score"] = semantic
            result["_freshness"] = 0.0
            continue
        freshness = compute_freshness(created_at, half_life_hours, now)
        result["_semantic_score"] = semantic
        result["_freshness"] = freshness
        result[score_key] = (1 - alpha) * semantic + alpha * freshness

    results.sort(key=lambda x: x.get(score_key, 0), reverse=True)
    return results


# ── Hebbian scoring ──────────────────────────────────────────────────


def compute_activation_strength(
    activation_count: int,
    max_count: int = 100,
) -> float:
    """Log-normalized activation strength in [0, 1].

    strength = log(1 + count) / log(1 + max_count)
    """
    if activation_count <= 0:
        return 0.0
    if max_count <= 0:
        max_count = 100
    raw = math.log(1 + activation_count) / math.log(1 + max_count)
    return min(raw, 1.0)


def compute_hebbian_boost(
    activation_count: int,
    co_activation_weight: float = 0.0,
    max_activation_count: int = 100,
) -> float:
    """Combined Hebbian boost from activation strength and co-activation weight.

    hebbian = 0.5 * activation_strength + 0.5 * co_activation_weight
    Both components in [0, 1], result in [0, 1].
    """
    strength = compute_activation_strength(activation_count, max_activation_count)
    co_weight = max(0.0, min(1.0, co_activation_weight))
    return 0.5 * strength + 0.5 * co_weight


def apply_hebbian_score(
    results: List[Dict[str, Any]],
    beta: float,
    alpha: float,
    half_life_hours: float,
    score_key: str = "score",
    time_key: str = "created_at",
    now: float = None,
    max_activation_count: int = 100,
    co_activation_weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Three-dimensional scoring: semantic + freshness + hebbian.

    final = (1 - alpha - beta) * semantic + alpha * freshness + beta * hebbian

    Falls back to two-dimensional if beta == 0.
    Preserves _semantic_score, _freshness, _hebbian_boost on each result.
    Returns results sorted by new score descending.
    """
    now = now or time.time()
    co_weights = co_activation_weights or {}

    # Clamp alpha + beta to not exceed 1.0
    if alpha + beta > 1.0:
        beta = max(0.0, 1.0 - alpha)

    semantic_weight = 1.0 - alpha - beta

    for result in results:
        semantic = result.get(score_key, 0.0)
        created_at = result.get(time_key, 0.0)

        # Freshness
        if created_at > 0:
            freshness = compute_freshness(created_at, half_life_hours, now)
        else:
            freshness = 0.0

        # Hebbian boost
        act_count = result.get("activation_count", 0)
        result_uuid = result.get("uuid", "")
        co_weight = co_weights.get(result_uuid, 0.0)
        hebbian = compute_hebbian_boost(act_count, co_weight, max_activation_count)

        result["_semantic_score"] = semantic
        result["_freshness"] = freshness
        result["_hebbian_boost"] = hebbian
        result[score_key] = semantic_weight * semantic + alpha * freshness + beta * hebbian

    results.sort(key=lambda x: x.get(score_key, 0), reverse=True)
    return results
