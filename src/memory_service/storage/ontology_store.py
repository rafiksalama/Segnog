"""
OntologyStore — entity-centric long-term memory backed by FalkorDB.

Each real-world entity (Person, Organization, Place, Event…) lives as a single
:OntologyNode with:
  - schema_type: Schema.org class name ("Person", "Organization", …)
  - summary:     Full prose summary of everything known — updated by REM worker
  - embedding:   vecf32 of the summary — primary retrieval vector

Write path (slow — REM worker only):
  upsert_node() → MERGE node → re-embed updated summary
  store_relates() → MERGE RELATES edge + ontological inference (symmetric / inverse)
  link_about()   → MERGE ABOUT edge from Episode to OntologyNode

Read path (fast — always embedding-only):
  search_nodes() → cosine similarity on summary embeddings
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .base_store import BaseStore, normalize_name
from ..schema_org import SchemaOrgOntology

logger = logging.getLogger(__name__)


class OntologyStore(BaseStore):
    """
    Entity-centric Ontology storage layer.

    Requires a SchemaOrgOntology instance for inference (symmetric/inverse edges).
    Shares the same FalkorDB graph as EpisodeStore and KnowledgeStore.
    """

    def __init__(
        self,
        graph,
        openai_client,
        embedding_model: str,
        ontology: SchemaOrgOntology,
        group_id: str = "default",
    ):
        super().__init__(graph, openai_client, embedding_model, group_id)
        self._ontology = ontology

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        """Create indexes on OntologyNode nodes if they don't exist."""
        index_queries = [
            "CREATE INDEX FOR (n:OntologyNode) ON (n.uuid)",
            "CREATE INDEX FOR (n:OntologyNode) ON (n.group_id)",
            "CREATE INDEX FOR (n:OntologyNode) ON (n.schema_type)",
            "CREATE INDEX FOR (n:OntologyNode) ON (n.name)",
            "CREATE INDEX FOR (n:OntologyNode) ON (n.updated_at)",
        ]
        for q in index_queries:
            try:
                await self._graph.query(q)
            except Exception:
                pass  # Index may already exist

        logger.debug("OntologyStore indexes ensured")

    # ------------------------------------------------------------------
    # Write: upsert node
    # ------------------------------------------------------------------

    async def upsert_node(
        self,
        name: str,
        schema_type: str,
        display_name: str,
        summary: str,
        group_id: Optional[str] = None,
    ) -> str:
        """
        MERGE an OntologyNode by (name, group_id).

        If it exists: update summary, display_name, schema_type, embedding, updated_at.
        If new: create with uuid, created_at, source_count=1.

        Returns the node's uuid.
        """
        gid = group_id or self._group_id
        norm = normalize_name(name)
        if not norm:
            raise ValueError(f"Cannot normalize name: {name!r}")

        # Validate and normalize schema_type against full Schema.org
        canonical_type = self._ontology.normalize_class(schema_type)

        embedding = await self._embed(summary)
        now = time.time()
        new_uuid = str(uuid4())

        # MERGE: match on (name, group_id), set all mutable fields
        result = await self._graph.query(
            """
            MERGE (n:OntologyNode {name: $name, group_id: $group_id})
            ON CREATE SET
                n.uuid         = $uuid,
                n.schema_type  = $schema_type,
                n.display_name = $display_name,
                n.summary      = $summary,
                n.embedding    = vecf32($embedding),
                n.created_at   = $now,
                n.updated_at   = $now,
                n.source_count = 1
            ON MATCH SET
                n.schema_type  = $schema_type,
                n.display_name = $display_name,
                n.summary      = $summary,
                n.embedding    = vecf32($embedding),
                n.updated_at   = $now,
                n.source_count = coalesce(n.source_count, 0) + 1
            RETURN n.uuid AS uuid
            """,
            params={
                "name": norm,
                "group_id": gid,
                "uuid": new_uuid,
                "schema_type": canonical_type,
                "display_name": display_name,
                "summary": summary,
                "embedding": embedding,
                "now": now,
            },
        )

        rows = self._parse_results(result)
        return rows[0]["uuid"] if rows else new_uuid

    # ------------------------------------------------------------------
    # Read: get single node
    # ------------------------------------------------------------------

    async def get_node(
        self,
        name: str,
        group_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch an OntologyNode by normalized name and group_id.
        Returns dict with all properties, or None if not found.
        """
        gid = group_id or self._group_id
        norm = normalize_name(name)

        result = await self._graph.ro_query(
            """
            MATCH (n:OntologyNode {name: $name, group_id: $group_id})
            RETURN
                n.uuid         AS uuid,
                n.schema_type  AS schema_type,
                n.display_name AS display_name,
                n.summary      AS summary,
                n.source_count AS source_count,
                n.created_at   AS created_at,
                n.updated_at   AS updated_at
            LIMIT 1
            """,
            params={"name": norm, "group_id": gid},
        )

        rows = self._parse_results(result)
        if rows:
            rows[0]["name"] = norm
            rows[0]["group_id"] = gid
            return rows[0]
        return None

    # ------------------------------------------------------------------
    # Read: vector search
    # ------------------------------------------------------------------

    async def search_nodes(
        self,
        embedding: List[float],
        top_k: int = 5,
        group_id: Optional[str] = None,
        min_score: float = 0.5,
        include_embedding: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Cosine similarity search against OntologyNode summary embeddings.

        Returns list of dicts sorted by score descending. Never traverses graph edges.
        """
        gid = group_id or self._group_id
        embedding_return = (
            ",\n                n.embedding AS embedding" if include_embedding else ""
        )

        result = await self._graph.ro_query(
            f"""
            MATCH (n:OntologyNode)
            WHERE n.group_id = $group_id
            WITH n,
                 (2 - vec.cosineDistance(n.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score >= $min_score
            RETURN
                n.uuid         AS uuid,
                n.name         AS name,
                n.schema_type  AS schema_type,
                n.display_name AS display_name,
                n.summary      AS summary,
                n.source_count AS source_count,
                n.updated_at   AS updated_at,
                score{embedding_return}
            ORDER BY score DESC
            LIMIT $top_k
            """,
            params={
                "group_id": gid,
                "query_vec": embedding,
                "min_score": min_score,
                "top_k": top_k,
            },
        )

        return self._parse_results(result)

    # ------------------------------------------------------------------
    # Write: RELATES edge + ontological inference
    # ------------------------------------------------------------------

    async def store_relates(
        self,
        subject_norm: str,
        predicate: str,
        object_norm: str,
        group_id: Optional[str] = None,
        confidence: float = 1.0,
    ) -> bool:
        """
        MERGE a RELATES edge between two OntologyNodes.

        Ontological inference (fired automatically):
          - Symmetric predicate (knows, spouse, sibling…): also store the reverse edge.
          - Declared inverse (memberOf ↔ member, parent ↔ children…): also store inverse edge.

        Both subject and object nodes must already exist (call upsert_node first).

        Returns:
            True if the forward edge was actually stored (both nodes existed), False otherwise.
        """
        gid = group_id or self._group_id
        canonical_pred = self._ontology.normalize_predicate(predicate)
        now = time.time()

        # Merge forward edge — only proceed with inference if this succeeded
        stored = await self._merge_relates_edge(
            subject_norm, canonical_pred, object_norm, gid, confidence, now
        )
        if not stored:
            return False

        # Symmetric inference
        if self._ontology.is_symmetric(canonical_pred):
            await self._merge_relates_edge(
                object_norm, canonical_pred, subject_norm, gid, confidence, now
            )

        # Inverse inference
        inverse = self._ontology.get_inverse(canonical_pred)
        if inverse and inverse != canonical_pred:
            await self._merge_relates_edge(object_norm, inverse, subject_norm, gid, confidence, now)

        return True

    async def _merge_relates_edge(
        self,
        subject_norm: str,
        predicate: str,
        object_norm: str,
        group_id: str,
        confidence: float,
        now: float,
    ) -> bool:
        """MERGE a single directed RELATES edge.

        Returns True if the edge was created or found, False if either node was missing.
        """
        try:
            result = await self._graph.query(
                """
                MATCH (a:OntologyNode {name: $subject, group_id: $group_id})
                MATCH (b:OntologyNode {name: $object, group_id: $group_id})
                MERGE (a)-[r:RELATES {predicate: $predicate, group_id: $group_id}]->(b)
                ON CREATE SET r.confidence = $confidence, r.created_at = $now
                ON MATCH SET  r.confidence = CASE
                    WHEN r.confidence < $confidence THEN $confidence
                    ELSE r.confidence
                END
                RETURN count(r) AS n
                """,
                params={
                    "subject": subject_norm,
                    "object": object_norm,
                    "group_id": group_id,
                    "predicate": predicate,
                    "confidence": confidence,
                    "now": now,
                },
            )
            # If MATCH found no nodes, result_set is empty (returns 0 rows)
            if result.result_set and result.result_set[0][0] > 0:
                return True
            logger.debug(
                "store_relates: no nodes found for (%s -[%s]-> %s) in group '%s'",
                subject_norm,
                predicate,
                object_norm,
                group_id,
            )
            return False
        except Exception as e:
            logger.warning(
                "store_relates edge failed (%s -[%s]-> %s): %s",
                subject_norm,
                predicate,
                object_norm,
                e,
            )
            return False

    # ------------------------------------------------------------------
    # Write: ABOUT edge (Episode → OntologyNode)
    # ------------------------------------------------------------------

    async def link_about(
        self,
        episode_uuid: str,
        entity_name: str,
        group_id: Optional[str] = None,
    ) -> None:
        """
        MERGE an ABOUT edge from an Episode to an OntologyNode.

        Creates provenance: episode ─[ABOUT]→ entity.
        Safe to call if episode or entity don't exist — uses MATCH so it's a no-op.
        """
        gid = group_id or self._group_id
        norm = normalize_name(entity_name)

        try:
            await self._graph.query(
                """
                MATCH (e:Episode {uuid: $ep_uuid})
                MATCH (n:OntologyNode {name: $entity_name, group_id: $group_id})
                MERGE (e)-[:ABOUT]->(n)
                """,
                params={
                    "ep_uuid": episode_uuid,
                    "entity_name": norm,
                    "group_id": gid,
                },
            )
        except Exception as exc:
            logger.warning("link_about failed (ep=%s entity=%s): %s", episode_uuid, norm, exc)

    # ------------------------------------------------------------------
    # Utility: list all nodes for a group
    # ------------------------------------------------------------------

    async def list_nodes(
        self,
        group_id: Optional[str] = None,
        schema_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List OntologyNodes for a group, optionally filtered by schema_type."""
        gid = group_id or self._group_id

        if schema_type:
            result = await self._graph.ro_query(
                """
                MATCH (n:OntologyNode {group_id: $group_id, schema_type: $schema_type})
                RETURN n.uuid AS uuid, n.name AS name, n.schema_type AS schema_type,
                       n.display_name AS display_name, n.source_count AS source_count,
                       n.updated_at AS updated_at
                ORDER BY n.updated_at DESC
                LIMIT $limit
                """,
                params={"group_id": gid, "schema_type": schema_type, "limit": limit},
            )
        else:
            result = await self._graph.ro_query(
                """
                MATCH (n:OntologyNode {group_id: $group_id})
                RETURN n.uuid AS uuid, n.name AS name, n.schema_type AS schema_type,
                       n.display_name AS display_name, n.source_count AS source_count,
                       n.updated_at AS updated_at
                ORDER BY n.updated_at DESC
                LIMIT $limit
                """,
                params={"group_id": gid, "limit": limit},
            )

        return self._parse_results(result)
