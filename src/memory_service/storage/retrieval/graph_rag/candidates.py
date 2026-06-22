"""Map entity PPR scores to retrievable Knowledge/CausalClaim candidates.

Given a relevance score per entity (from PPR), fetch the Knowledge nodes and
CausalClaims linked to those entities and attach the summed PPR mass of their
linked entities. Bounded by `cap`. All reads use ro_query (timeout-bounded).
"""
from typing import Any, Dict, List


class CandidateMapper:
    def __init__(self, graph):
        self._graph = graph

    async def map_candidates(
        self, entity_scores: Dict[str, float], group_id: str, cap: int = 200
    ) -> List[Dict[str, Any]]:
        if not entity_scores:
            return []
        names = list(entity_scores.keys())
        candidates: List[Dict[str, Any]] = []

        # Knowledge linked to these entities via its source Episode's ABOUT edges.
        kn = await self._graph.ro_query(
            """
            MATCH (k:Knowledge {group_id: $gid})-[:DERIVED_FROM]->(:Episode)-[:ABOUT]->(n:OntologyNode)
            WHERE n.name IN $names
            WITH k, collect(DISTINCT n.name) AS ents
            RETURN k.uuid AS uuid, k.content AS content, k.knowledge_type AS ktype,
                   k.confidence AS confidence, k.created_at AS created_at,
                   COALESCE(k.activation_count, 0) AS activation_count, ents
            LIMIT $cap
            """,
            params={"gid": group_id, "names": names, "cap": cap},
        )
        for row in (kn.result_set or []):
            ents = row[6] or []
            ppr_mass = sum(entity_scores.get(e, 0.0) for e in ents)
            candidates.append({
                "uuid": row[0], "content": row[1], "knowledge_type": row[2],
                "confidence": row[3], "created_at": row[4],
                "activation_count": row[5], "ppr_mass": ppr_mass,
                "source": "knowledge",
            })

        # CausalClaims whose cause/effect entity is in scope.
        cz = await self._graph.ro_query(
            """
            MATCH (c:CausalClaim {group_id: $gid})-[:CAUSE_ENTITY|EFFECT_ENTITY]->(n:OntologyNode)
            WHERE n.name IN $names
            OPTIONAL MATCH (:Knowledge)-[s:SUPPORTS]->(c)
            WITH c, collect(DISTINCT n.name) AS ents, COALESCE(sum(s.weight), 0.0) AS support
            RETURN c.uuid AS uuid, c.cause_summary AS cause, c.effect_summary AS effect,
                   c.causal_type AS ctype, c.confidence AS confidence,
                   c.created_at AS created_at, ents, support
            LIMIT $cap
            """,
            params={"gid": group_id, "names": names, "cap": cap},
        )
        for row in (cz.result_set or []):
            ents = row[6] or []
            ppr_mass = sum(entity_scores.get(e, 0.0) for e in ents)
            candidates.append({
                "uuid": row[0],
                "content": f"{row[1]} —[{row[3]}]→ {row[2]}",
                "knowledge_type": "causal_claim",
                "confidence": row[4], "created_at": row[5],
                "activation_count": 0, "ppr_mass": ppr_mass,
                "causal_evidence": float(row[7] or 0.0),
                "causal_type": row[3], "source": "causal_claim",
            })
        return candidates
