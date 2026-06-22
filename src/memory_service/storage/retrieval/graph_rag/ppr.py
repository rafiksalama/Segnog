"""Seeded Personalized PageRank over a small in-memory weighted digraph.

Pure function — no I/O. Used to propagate query relevance across the entity
graph (RELATES + causal edges). Power-iteration on a scipy sparse column-
stochastic matrix; the teleport vector is the (normalised) seed distribution.
"""
from typing import Dict, List, Tuple

import numpy as np
from scipy.sparse import csr_matrix


def personalized_pagerank(
    nodes: List[str],
    edges: List[Tuple[str, str, float]],   # (src, dst, weight)
    seeds: Dict[str, float],               # node -> teleport mass (unnormalised ok)
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Dict[str, float]:
    """Return {node: PPR score} biased toward `seeds`. Scores sum to 1.0.

    Empty graph or empty/zero seeds → {}.
    """
    if not nodes or not seeds:
        return {}
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)

    # Build weighted adjacency (src->dst), then column-normalise to a transition matrix.
    rows, cols, data = [], [], []
    for src, dst, w in edges:
        if src in idx and dst in idx and w > 0:
            rows.append(idx[dst])
            cols.append(idx[src])
            data.append(float(w))
    A = csr_matrix((data, (rows, cols)), shape=(n, n)) if data else csr_matrix((n, n))
    col_sums = np.asarray(A.sum(axis=0)).ravel()
    col_sums[col_sums == 0] = 1.0
    M = A.multiply(1.0 / col_sums)          # column-stochastic

    # Teleport vector from seeds (normalised).
    tele = np.zeros(n)
    for node, mass in seeds.items():
        if node in idx and mass > 0:
            tele[idx[node]] += float(mass)
    if tele.sum() == 0:
        return {}
    tele /= tele.sum()

    r = tele.copy()
    for _ in range(max_iter):
        r_next = damping * (M @ r) + (1.0 - damping) * tele
        if np.abs(r_next - r).sum() < tol:
            r = r_next
            break
        r = r_next
    r = r / r.sum()
    return {nodes[i]: float(r[i]) for i in range(n)}
