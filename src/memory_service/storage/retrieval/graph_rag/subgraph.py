"""Build a bounded, weighted entity subgraph for PPR from FalkorDB.

Expands outward from seed entities up to `max_hops`, collecting RELATES
(co-occurrence/inferred) edges and causal edges (derived from CausalClaim
CAUSE_ENTITY/EFFECT_ENTITY). All reads use ro_query (inherits the FalkorDB
query timeout); every query is LIMIT-capped and the hop count is bounded.
"""

from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

# Causal type -> base propagation weight; multiplied by the claim's confidence.
_CAUSAL_BASE_W = {"causes": 1.0, "enables": 0.8, "prevents": 0.7, "inhibits": 0.7}
_EDGE_LIMIT = 2000


class PPRSubgraphBuilder:
    def __init__(self, graph):
        self._graph = graph  # FalkorDB graph handle (has .ro_query)

    async def build(
        self, seed_names: List[str], group_id: str, max_hops: int = 2
    ) -> Tuple[List[str], List[Tuple[str, str, float]]]:
        """Return (node_names, weighted_edges) for the seed neighbourhood."""
        if not seed_names:
            return [], []
        frontier = set(seed_names)
        all_nodes = set(seed_names)
        edges: List[Tuple[str, str, float]] = []

        for _hop in range(max_hops):
            if not frontier:
                break
            new_nodes = set()

            # RELATES (symmetric) edges from the current frontier.
            rel = await self._graph.ro_query(
                """
                MATCH (a:OntologyNode)-[r:RELATES]-(b:OntologyNode)
                WHERE a.name IN $frontier
                RETURN a.name AS src, b.name AS dst, COALESCE(r.weight, 1.0) AS w
                LIMIT $lim
                """,
                params={"frontier": list(frontier), "lim": _EDGE_LIMIT},
            )
            for row in rel.result_set or []:
                src, dst, w = row[0], row[1], float(row[2] or 1.0)
                edges.append((src, dst, w))
                edges.append((dst, src, w))  # symmetric
                if dst not in all_nodes:
                    new_nodes.add(dst)

            # Causal edges: cause_entity -> effect_entity via CausalClaim (directed).
            cz = await self._graph.ro_query(
                """
                MATCH (ce:OntologyNode)<-[:CAUSE_ENTITY]-(c:CausalClaim)-[:EFFECT_ENTITY]->(ee:OntologyNode)
                WHERE ce.name IN $frontier OR ee.name IN $frontier
                RETURN ce.name AS src, ee.name AS dst,
                       COALESCE(c.causal_type, 'causes') AS ctype,
                       COALESCE(c.confidence, 0.5) AS conf
                LIMIT $lim
                """,
                params={"frontier": list(frontier), "lim": _EDGE_LIMIT},
            )
            for row in cz.result_set or []:
                src, dst, ctype, conf = row[0], row[1], row[2], float(row[3] or 0.5)
                w = _CAUSAL_BASE_W.get(ctype, 1.0) * conf
                edges.append((src, dst, w))  # directed (causal)
                for nm in (src, dst):
                    if nm not in all_nodes:
                        new_nodes.add(nm)

            all_nodes |= new_nodes
            frontier = new_nodes

        return list(all_nodes), edges
