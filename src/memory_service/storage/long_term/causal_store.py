"""
CausalClaimStore — causal belief network backed by FalkorDB.

Each causal assertion lives as a :CausalClaim node with:
  - cause_summary / effect_summary: what causes what
  - mechanism: how/why the causal link holds
  - confidence: evidence-weighted ratio (0-1), revised as evidence arrives
  - embedding: vecf32 of "{cause} causes {effect}" for retrieval

Evidence edges:
  (:Knowledge)-[:SUPPORTS {weight}]->(:CausalClaim)
  (:Knowledge)-[:CONTRADICTS {weight}]->(:CausalClaim)

Entity linkage:
  (:CausalClaim)-[:CAUSE_ENTITY]->(:OntologyNode)
  (:CausalClaim)-[:EFFECT_ENTITY]->(:OntologyNode)

Chaining:
  (:CausalClaim)-[:CAUSES]->(:CausalClaim)
  (:CausalChain)-[:CHAIN_STEP {position}]->(:CausalClaim)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .base_store import BaseStore, normalize_name

logger = logging.getLogger(__name__)


class CausalClaimStore(BaseStore):
    """Causal belief network storage layer.

    Shares the same FalkorDB graph as all other stores.
    """

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        for q in [
            "CREATE INDEX FOR (c:CausalClaim) ON (c.uuid)",
            "CREATE INDEX FOR (c:CausalClaim) ON (c.group_id)",
            "CREATE INDEX FOR (c:CausalClaim) ON (c.status)",
            "CREATE INDEX FOR (c:CausalClaim) ON (c.confidence)",
            "CREATE INDEX FOR (c:CausalClaim) ON (c.updated_at)",
            "CREATE INDEX FOR (ch:CausalChain) ON (ch.uuid)",
            "CREATE INDEX FOR (ch:CausalChain) ON (ch.group_id)",
        ]:
            try:
                await self._graph.query(q)
            except Exception:
                pass
        logger.debug("CausalClaimStore indexes ensured")

    # ------------------------------------------------------------------
    # Write: upsert claim
    # ------------------------------------------------------------------

    CAUSAL_TYPES = {"causes", "enables", "prevents", "inhibits"}

    async def upsert_claim(
        self,
        cause_summary: str,
        effect_summary: str,
        mechanism: str = "",
        confidence: float = 0.8,
        causal_type: str = "causes",
        cause_entity: Optional[str] = None,
        effect_entity: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> str:
        """MERGE a CausalClaim by normalized (cause+effect) — global KG.

        Returns the claim's uuid.
        """
        gid = group_id or self._group_id
        # Merge key: normalized concatenation of cause and effect
        cause_norm = normalize_name(cause_summary)
        effect_norm = normalize_name(effect_summary)
        merge_key = f"{cause_norm}--{effect_norm}"

        ctype = causal_type if causal_type in self.CAUSAL_TYPES else "causes"
        embed_text = f"{cause_summary} {ctype} {effect_summary}"
        if mechanism:
            embed_text += f" because {mechanism}"
        embedding = await self._embed(embed_text)
        now = time.time()
        new_uuid = str(uuid4())

        result = await self._graph.query(
            """
            MERGE (c:CausalClaim {merge_key: $merge_key})
            ON CREATE SET
                c.uuid           = $uuid,
                c.cause_summary  = $cause_summary,
                c.effect_summary = $effect_summary,
                c.mechanism      = $mechanism,
                c.confidence     = $confidence,
                c.certainty      = 0.0,
                c.causal_type    = $causal_type,
                c.evidence_count = 0,
                c.status         = 'active',
                c.embedding      = vecf32($embedding),
                c.created_at     = $now,
                c.updated_at     = $now
            ON MATCH SET
                c.mechanism      = CASE WHEN size($mechanism) > size(coalesce(c.mechanism, ''))
                                        THEN $mechanism ELSE c.mechanism END,
                c.confidence     = $confidence,
                c.embedding      = vecf32($embedding),
                c.updated_at     = $now
            RETURN c.uuid AS uuid
            """,
            params={
                "merge_key": merge_key,
                "group_id": gid,
                "uuid": new_uuid,
                "cause_summary": cause_summary,
                "effect_summary": effect_summary,
                "mechanism": mechanism,
                "causal_type": ctype,
                "confidence": max(0.0, min(1.0, confidence)),
                "embedding": embedding,
                "now": now,
            },
        )

        rows = self._parse_results(result)
        claim_uuid = rows[0]["uuid"] if rows else new_uuid

        # Link to OntologyNodes if entity names provided
        if cause_entity:
            await self._link_entity(claim_uuid, cause_entity, "CAUSE_ENTITY", gid)
        if effect_entity:
            await self._link_entity(claim_uuid, effect_entity, "EFFECT_ENTITY", gid)

        return claim_uuid

    async def _link_entity(
        self, claim_uuid: str, entity_name: str, edge_type: str, group_id: str
    ) -> None:
        norm = normalize_name(entity_name)
        try:
            await self._graph.query(
                f"""
                MATCH (c:CausalClaim {{uuid: $claim_uuid}})
                MATCH (n:OntologyNode {{name: $entity_name}})
                MERGE (c)-[:{edge_type}]->(n)
                """,
                params={
                    "claim_uuid": claim_uuid,
                    "entity_name": norm,
                    "group_id": group_id,
                },
            )
        except Exception as e:
            logger.debug("_link_entity %s failed: %s", edge_type, e)

    # ------------------------------------------------------------------
    # Write: add evidence
    # ------------------------------------------------------------------

    async def add_evidence(
        self,
        claim_uuid: str,
        knowledge_uuid: str,
        direction: str = "supports",
        weight: Optional[float] = None,
    ) -> None:
        """Add a SUPPORTS or CONTRADICTS edge from Knowledge to CausalClaim.

        If weight is None, uses the Knowledge node's own confidence as the
        edge weight — stronger sources produce stronger evidence.
        """
        edge_type = "SUPPORTS" if direction == "supports" else "CONTRADICTS"
        try:
            await self._graph.query(
                f"""
                MATCH (k:Knowledge {{uuid: $kn_uuid}})
                MATCH (c:CausalClaim {{uuid: $claim_uuid}})
                WITH k, c, CASE WHEN $weight < 0 THEN coalesce(k.confidence, 0.5) ELSE $weight END AS w
                MERGE (k)-[r:{edge_type}]->(c)
                ON CREATE SET r.weight = w, r.created_at = $now
                ON MATCH SET r.weight = w
                """,
                params={
                    "kn_uuid": knowledge_uuid,
                    "claim_uuid": claim_uuid,
                    "weight": weight if weight is not None else -1.0,
                    "now": time.time(),
                },
            )
            # Increment evidence count
            await self._graph.query(
                """
                MATCH (c:CausalClaim {uuid: $uuid})
                SET c.evidence_count = coalesce(c.evidence_count, 0) + 1
                """,
                params={"uuid": claim_uuid},
            )
        except Exception as e:
            logger.warning("add_evidence failed: %s", e)

    # ------------------------------------------------------------------
    # Write: revise beliefs
    # ------------------------------------------------------------------

    async def revise_beliefs(self, group_id: Optional[str] = None) -> int:
        """Recompute confidence and certainty for all active claims.

        Confidence uses Laplace-smoothed evidence ratio:
            (support + 1) / (support + contradict + 2)

        Certainty tracks how much evidence backs the claim:
            1 - 1 / (1 + evidence_count)
        0 evidence → 0.0 certainty, 1 → 0.5, 4 → 0.8, 9 → 0.9.

        No-evidence claims decay toward 0.5 via time-based exponential decay:
            0.5 + (conf - 0.5) * exp(-λ * hours_since_update)
        with λ = 0.01 (half-life ≈ 69 hours ≈ 3 days).

        Returns number of claims revised.
        """
        gid = group_id or self._group_id
        now = time.time()
        result = await self._graph.query(
            """
            MATCH (c:CausalClaim)
            WHERE c.status <> 'refuted'
            OPTIONAL MATCH (k1:Knowledge)-[s:SUPPORTS]->(c)
            OPTIONAL MATCH (k2:Knowledge)-[d:CONTRADICTS]->(c)
            WITH c,
                 coalesce(sum(s.weight), 0) AS support_total,
                 coalesce(sum(d.weight), 0) AS contradict_total,
                 count(DISTINCT s) + count(DISTINCT d) AS obs_count
            WITH c, support_total, contradict_total, obs_count,
                 CASE
                     WHEN support_total + contradict_total > 0 THEN
                         // Laplace-smoothed evidence ratio (alpha=1 prior).
                         (support_total + 1.0) / (support_total + contradict_total + 2.0)
                     ELSE
                         // Time-based exponential decay toward 0.5.
                         // hours_elapsed = (now - updated_at) / 3600, λ = 0.01
                         0.5 + (c.confidence - 0.5) * exp(-0.01 * ($now - coalesce(c.updated_at, $now)) / 3600.0)
                 END AS new_conf,
                 // Certainty: 0 when no evidence, approaches 1 as evidence grows
                 1.0 - 1.0 / (1.0 + obs_count) AS new_certainty
            SET c.confidence = new_conf,
                c.certainty = new_certainty,
                c.evidence_count = obs_count,
                c.status = CASE
                    WHEN new_conf < 0.05 THEN 'refuted'
                    WHEN new_conf < 0.2  THEN 'weakened'
                    ELSE 'active'
                END,
                c.updated_at = $now
            RETURN count(c) AS revised
            """,
            params={"group_id": gid, "now": now},
        )
        revised = result.result_set[0][0] if result.result_set else 0
        if revised:
            logger.info("Revised %d causal beliefs for group %s", revised, gid)
        return revised

    async def auto_chain(self, group_id: Optional[str] = None) -> int:
        """Auto-link causal claims via shared entities (graph-path discovery).

        Creates A-[:CAUSES]->B when A's effect entity is the same OntologyNode
        as B's cause entity — i.e. the two claims share a real-world entity
        that is the effect of one and the cause of the other.

        This replaces the previous embedding-similarity approach which confused
        semantic relatedness with actual causal linkage.

        Returns number of CAUSES edges created.
        """
        gid = group_id or self._group_id
        try:
            result = await self._graph.query(
                """
                MATCH (a:CausalClaim)-[:EFFECT_ENTITY]->(n:OntologyNode)<-[:CAUSE_ENTITY]-(b:CausalClaim)
                WHERE a.uuid <> b.uuid
                  AND a.status <> 'refuted'
                  AND b.status <> 'refuted'
                MERGE (a)-[r:CAUSES]->(b)
                ON CREATE SET r.provenance = 'transitive', r.created_at = $now
                RETURN count(*) AS created
                """,
                params={"now": time.time()},
            )
            created = result.result_set[0][0] if result.result_set else 0
            if created:
                logger.info("Auto-chained %d CAUSES edges for group %s", created, gid)
            return created
        except Exception as e:
            logger.debug("auto_chain failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Read: get single claim
    # ------------------------------------------------------------------

    async def get_claim(self, uuid: str) -> Optional[Dict[str, Any]]:
        result = await self._graph.ro_query(
            """
            MATCH (c:CausalClaim {uuid: $uuid})
            RETURN c.uuid AS uuid, c.group_id AS group_id,
                   c.cause_summary AS cause_summary, c.effect_summary AS effect_summary,
                   c.mechanism AS mechanism, c.causal_type AS causal_type,
                   c.confidence AS confidence,
                   c.certainty AS certainty, c.evidence_count AS evidence_count,
                   c.status AS status,
                   c.created_at AS created_at, c.updated_at AS updated_at
            LIMIT 1
            """,
            params={"uuid": uuid},
        )
        rows = self._parse_results(result)
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Read: vector search
    # ------------------------------------------------------------------

    async def search_claims(
        self,
        embedding: List[float],
        top_k: int = 5,
        group_id: Optional[str] = None,
        min_score: float = 0.4,
    ) -> List[Dict[str, Any]]:
        gid = group_id or self._group_id
        result = await self._graph.ro_query(
            """
            MATCH (c:CausalClaim)
            WHERE c.status <> 'refuted'
            WITH c,
                 (2 - vec.cosineDistance(c.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score >= $min_score
            RETURN c.uuid AS uuid, c.cause_summary AS cause_summary,
                   c.effect_summary AS effect_summary, c.mechanism AS mechanism,
                   c.confidence AS confidence, c.certainty AS certainty,
                   c.evidence_count AS evidence_count,
                   c.status AS status, c.created_at AS created_at, score
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
    # Read: list claims
    # ------------------------------------------------------------------

    async def list_claims(
        self,
        group_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        conditions = []
        if group_id:
            conditions.append("c.group_id = $group_id")
        if status:
            conditions.append("c.status = $status")
        where = " AND ".join(conditions) if conditions else "true"
        result = await self._graph.ro_query(
            f"""
            MATCH (c:CausalClaim)
            WHERE {where}
            RETURN c.uuid AS uuid, c.cause_summary AS cause_summary,
                   c.effect_summary AS effect_summary, c.mechanism AS mechanism,
                   c.confidence AS confidence, c.certainty AS certainty,
                   c.evidence_count AS evidence_count,
                   c.status AS status, c.updated_at AS updated_at
            ORDER BY c.confidence DESC
            LIMIT $limit
            """,
            params={"group_id": group_id or "", "status": status or "", "limit": limit},
        )
        return self._parse_results(result)

    # ------------------------------------------------------------------
    # Read: explain (evidence trail)
    # ------------------------------------------------------------------

    async def explain_claim(self, uuid: str) -> Dict[str, Any]:
        """Return claim with all SUPPORTS and CONTRADICTS evidence."""
        claim = await self.get_claim(uuid)
        if not claim:
            return {}

        supports = await self._graph.ro_query(
            """
            MATCH (k:Knowledge)-[s:SUPPORTS]->(c:CausalClaim {uuid: $uuid})
            RETURN k.uuid AS uuid, k.content AS content,
                   k.knowledge_type AS knowledge_type, s.weight AS weight
            ORDER BY s.weight DESC
            """,
            params={"uuid": uuid},
        )
        contradicts = await self._graph.ro_query(
            """
            MATCH (k:Knowledge)-[d:CONTRADICTS]->(c:CausalClaim {uuid: $uuid})
            RETURN k.uuid AS uuid, k.content AS content,
                   k.knowledge_type AS knowledge_type, d.weight AS weight
            ORDER BY d.weight DESC
            """,
            params={"uuid": uuid},
        )

        claim["supports"] = self._parse_results(supports)
        claim["contradicts"] = self._parse_results(contradicts)
        return claim

    # ------------------------------------------------------------------
    # Write: causal chain
    # ------------------------------------------------------------------

    async def build_chain(
        self,
        claim_uuids: List[str],
        description: str,
        group_id: Optional[str] = None,
    ) -> str:
        """Create a CausalChain linking ordered claims."""
        gid = group_id or self._group_id
        chain_uuid = str(uuid4())
        now = time.time()

        await self._graph.query(
            """
            CREATE (ch:CausalChain {
                uuid: $uuid, group_id: $group_id,
                description: $description, created_at: $now
            })
            """,
            params={
                "uuid": chain_uuid,
                "group_id": gid,
                "description": description,
                "now": now,
            },
        )

        for i, claim_uuid in enumerate(claim_uuids):
            await self._graph.query(
                """
                MATCH (ch:CausalChain {uuid: $chain_uuid})
                MATCH (c:CausalClaim {uuid: $claim_uuid})
                MERGE (ch)-[r:CHAIN_STEP]->(c)
                ON CREATE SET r.position = $position
                """,
                params={
                    "chain_uuid": chain_uuid,
                    "claim_uuid": claim_uuid,
                    "position": i,
                },
            )

        # Also link sequential claims with CAUSES edges
        for i in range(len(claim_uuids) - 1):
            await self._graph.query(
                """
                MATCH (a:CausalClaim {uuid: $a_uuid})
                MATCH (b:CausalClaim {uuid: $b_uuid})
                MERGE (a)-[r:CAUSES]->(b)
                ON CREATE SET r.provenance = 'direct', r.created_at = $now
                """,
                params={"a_uuid": claim_uuids[i], "b_uuid": claim_uuids[i + 1], "now": time.time()},
            )

        return chain_uuid
