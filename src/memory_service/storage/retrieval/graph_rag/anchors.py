"""Resolve a query to seed OntologyNode entities for PPR.

Reuses OntologyStore.search_nodes (cosine over entity-summary embeddings) to
find the entities a query is "about", which become the PPR teleport seeds.
"""
from typing import Dict


class EntityAnchorResolver:
    def __init__(self, ontology_store, embed_fn):
        self._onto = ontology_store          # OntologyStore
        self._embed = embed_fn               # async callable: str -> List[float]

    async def resolve(
        self, query: str, group_id: str, top_n: int = 10, min_score: float = 0.5,
        query_embedding=None,
    ) -> Dict[str, float]:
        """Return {entity_name: seed_mass} where mass = similarity score."""
        embedding = query_embedding if query_embedding is not None else await self._embed(query)
        nodes = await self._onto.search_nodes(
            embedding=embedding, top_k=top_n, group_id=group_id, min_score=min_score
        )
        seeds: Dict[str, float] = {}
        for n in nodes:
            name = n.get("name") or n.get("display_name")
            score = n.get("score", 0.0)
            if name and score > 0:
                seeds[name] = float(score)
        return seeds
