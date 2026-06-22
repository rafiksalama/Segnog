"""Orchestrate causal-aware Graph RAG retrieval for knowledge search.

Stages: embed query once -> vector seed (index-backed) + entity anchors ->
bounded entity+causal subgraph -> seeded PPR -> map entity scores to
Knowledge/CausalClaim candidates -> score EVERY candidate against the query
vector -> blended rerank. Falls back to plain vector hits when no entities
anchor the query.

Query relevance (vector_score) is computed for *every* candidate, including
graph-expanded ones, so query-independent graph-central hubs cannot dominate
the ranking (the failure mode the first live benchmark exposed).
"""
import logging
from typing import Any, Dict, List

from .anchors import EntityAnchorResolver
from .subgraph import PPRSubgraphBuilder
from .candidates import CandidateMapper
from .ppr import personalized_pagerank
from .rerank import rerank
from ..scoring import compute_freshness
from ....config import get_search_setting

logger = logging.getLogger(__name__)

_TEMPORAL_HALF_LIFE_HOURS = 720.0  # ~30 days


class GraphRetriever:
    def __init__(self, knowledge_store, ontology_store, graph):
        self._kn = knowledge_store
        self._graph = graph
        self._anchors = EntityAnchorResolver(ontology_store, knowledge_store._embed)
        self._subgraph = PPRSubgraphBuilder(graph)
        self._candidates = CandidateMapper(graph)

    async def search(self, query: str, group_id: str, top_k: int = 10) -> List[Dict[str, Any]]:
        q_emb = await self._kn._embed(query)

        # Stage 1: vector seed (index-backed) — for non-entity hits + a relevance floor.
        vector_hits = await self._kn.search_by_vector(query, top_k=top_k * 2)
        vec_by_uuid = {h["uuid"]: h.get("score", 0.0) for h in vector_hits}

        # Stage 1b: entity anchors (PPR seeds) — tightly scoped so PPR is query-anchored.
        seeds = await self._anchors.resolve(
            query, group_id,
            top_n=int(get_search_setting("ppr_seed_top_n", 6)),
            min_score=float(get_search_setting("ppr_min_seed_score", 0.7)),
            query_embedding=q_emb,
        )
        if not seeds:
            return vector_hits[:top_k]   # no entities matched → plain vector search

        # Stage 2: bounded subgraph (RELATES + causal edges).
        nodes, edges = await self._subgraph.build(
            list(seeds.keys()), group_id,
            max_hops=int(get_search_setting("ppr_max_hops", 2)),
        )
        # Stage 3: seeded Personalized PageRank.
        entity_scores = personalized_pagerank(
            nodes, edges, seeds, damping=float(get_search_setting("ppr_damping", 0.85))
        )
        # Stage 4: map to Knowledge/CausalClaim candidates.
        cands = await self._candidates.map_candidates(
            entity_scores, group_id, cap=int(get_search_setting("candidate_cap", 200))
        )
        # Merge in vector-only hits not already entity-linked.
        seen = {c["uuid"] for c in cands}
        for h in vector_hits:
            if h["uuid"] not in seen:
                cands.append({**h, "ppr_mass": 0.0, "source": "vector"})

        if not cands:
            return vector_hits[:top_k]

        # Stage 4b (the fix): real query relevance for EVERY candidate.
        vscore = await self._score_by_vector([c["uuid"] for c in cands], q_emb)

        _norm(cands, "ppr_mass")
        for c in cands:
            c["vector_score"] = vscore.get(c["uuid"], vec_by_uuid.get(c["uuid"], 0.0))
            c["hebbian"] = min(1.0, (c.get("activation_count", 0) or 0) / 10.0)
            c["temporal"] = compute_freshness(
                c.get("created_at", 0.0) or 0.0, _TEMPORAL_HALF_LIFE_HOURS
            )
            c.setdefault("causal_evidence", 0.0)

        weights = {k: float(get_search_setting(k, d)) for k, d in {
            "w_ppr": 0.45, "w_vector": 0.30, "w_causal_evidence": 0.10,
            "w_temporal": 0.10, "w_hebbian": 0.05,
        }.items()}
        return rerank(cands, weights, top_k=top_k)

    async def _score_by_vector(self, uuids: List[str], q_emb: List[float]) -> Dict[str, float]:
        """Cosine similarity of each candidate (Knowledge or CausalClaim) vs the query."""
        if not uuids:
            return {}
        res = await self._graph.ro_query(
            """
            UNWIND $uuids AS u
            OPTIONAL MATCH (k:Knowledge {uuid: u})
            OPTIONAL MATCH (c:CausalClaim {uuid: u})
            WITH u, COALESCE(k, c) AS n
            WHERE n IS NOT NULL AND n.embedding IS NOT NULL
            RETURN u AS uuid, (2 - vec.cosineDistance(n.embedding, vecf32($qvec))) / 2 AS vscore
            """,
            params={"uuids": uuids, "qvec": q_emb},
        )
        return {row[0]: float(row[1]) for row in (res.result_set or [])}


def _norm(items: List[Dict[str, Any]], key: str) -> None:
    mx = max((i.get(key, 0.0) for i in items), default=0.0)
    if mx > 0:
        for i in items:
            i[key] = i.get(key, 0.0) / mx
