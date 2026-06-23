"""Orchestrate causal-aware Graph RAG retrieval for knowledge + episode search.

Stages: embed query once -> vector seed (index-backed) + entity anchors ->
bounded entity+causal subgraph -> seeded PPR -> map entity scores to
candidates (Knowledge/CausalClaim, or Episode) -> score EVERY candidate
against the query vector -> blended rerank. Falls back to plain vector hits
when no entities anchor the query.

Query relevance (vector_score) is computed for *every* candidate, including
graph-expanded ones, so query-independent graph-central hubs cannot dominate
the ranking (the failure mode the first live benchmark exposed).
"""
import logging
from typing import Any, Dict, List, Optional

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
    def __init__(self, knowledge_store, ontology_store, graph, episode_store=None):
        self._kn = knowledge_store
        self._ep = episode_store
        self._graph = graph
        embed_fn = (knowledge_store or episode_store)._embed
        self._anchors = EntityAnchorResolver(ontology_store, embed_fn)
        self._subgraph = PPRSubgraphBuilder(graph)
        self._candidates = CandidateMapper(graph)

    # ── Shared stages ──────────────────────────────────────────────────────

    async def _seed_entities(self, query: str, group_id: str, q_emb) -> Dict[str, float]:
        return await self._anchors.resolve(
            query, group_id,
            top_n=int(get_search_setting("ppr_seed_top_n", 6)),
            min_score=float(get_search_setting("ppr_min_seed_score", 0.7)),
            query_embedding=q_emb,
        )

    async def _ppr(self, seeds: Dict[str, float], group_id: str) -> Dict[str, float]:
        nodes, edges = await self._subgraph.build(
            list(seeds.keys()), group_id,
            max_hops=int(get_search_setting("ppr_max_hops", 2)),
        )
        return personalized_pagerank(
            nodes, edges, seeds, damping=float(get_search_setting("ppr_damping", 0.85))
        )

    async def _finalize(self, cands, vector_hits, vec_by_uuid, q_emb, top_k):
        """Merge vector hits, score every candidate vs query vector, blend, rerank."""
        seen = {c["uuid"] for c in cands}
        for h in vector_hits:
            if h["uuid"] not in seen:
                cands.append({**h, "ppr_mass": 0.0, "source": "vector"})
        if not cands:
            return vector_hits[:top_k]

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

    # ── Knowledge search ───────────────────────────────────────────────────

    async def search(self, query: str, group_id: str, top_k: int = 10) -> List[Dict[str, Any]]:
        q_emb = await self._kn._embed(query)
        vector_hits = await self._kn.search_by_vector(query, top_k=top_k * 2)
        vec_by_uuid = {h["uuid"]: h.get("score", 0.0) for h in vector_hits}

        seeds = await self._seed_entities(query, group_id, q_emb)
        if not seeds:
            return vector_hits[:top_k]

        entity_scores = await self._ppr(seeds, group_id)
        cands = await self._candidates.map_candidates(
            entity_scores, group_id, cap=int(get_search_setting("candidate_cap", 200))
        )
        return await self._finalize(cands, vector_hits, vec_by_uuid, q_emb, top_k)

    # ── Episode search ─────────────────────────────────────────────────────

    async def search_episodes(
        self, query: str, group_id: str, top_k: int = 25,
        episode_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self._ep is None:
            raise RuntimeError("GraphRetriever has no episode_store")
        q_emb = await self._ep._embed(query)
        vector_hits = await self._ep.search_episodes(
            query, top_k=top_k * 2, episode_type=episode_type
        )
        vec_by_uuid = {h["uuid"]: h.get("score", 0.0) for h in vector_hits}

        seeds = await self._seed_entities(query, group_id, q_emb)
        if not seeds:
            return vector_hits[:top_k]

        entity_scores = await self._ppr(seeds, group_id)
        cands = await self._candidates.map_episode_candidates(
            entity_scores, group_id,
            cap=int(get_search_setting("candidate_cap", 200)),
            episode_type=episode_type,
        )
        return await self._finalize(cands, vector_hits, vec_by_uuid, q_emb, top_k)

    # ── Per-candidate query relevance ──────────────────────────────────────

    async def _score_by_vector(self, uuids: List[str], q_emb: List[float]) -> Dict[str, float]:
        """Cosine similarity of each candidate (Knowledge, CausalClaim, or Episode) vs query."""
        if not uuids:
            return {}
        res = await self._graph.ro_query(
            """
            UNWIND $uuids AS u
            OPTIONAL MATCH (k:Knowledge {uuid: u})
            OPTIONAL MATCH (c:CausalClaim {uuid: u})
            OPTIONAL MATCH (e:Episode {uuid: u})
            WITH u, COALESCE(k, c, e) AS n
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
