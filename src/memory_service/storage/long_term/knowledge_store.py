"""
Knowledge Store

Persistent knowledge graph on FalkorDB with vector + label hybrid search.
Shares the same FalkorDB graph as EpisodeStore and ArtifactStore.

Write path: extract entries → batch embed (~200ms) → store Knowledge + Label nodes → done.
Search path: embed query (~200ms) → hybrid vector + label search (~50ms) → done.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .base_store import BaseStore, normalize_name

logger = logging.getLogger(__name__)

# Backwards-compatible alias
normalize_label = normalize_name

# Embedding dimension for the configured model (google/embeddinggemma-300m = 768).
# Must match the model in settings.toml [embeddings].model. The vector index is
# created with this dimension; if the model changes, the index must be rebuilt.
EMBEDDING_DIM = 768

# Filtered-ANN over-fetch: db.idx.vector.queryNodes returns the globally nearest
# nodes, which we then filter by group_id/type/garbage. We over-fetch so enough
# survive the post-filter. For a small group in a large multi-tenant graph the ANN
# may still under-deliver — search_by_vector falls back to the brute-force scan
# (cheap, bounded by the group_id range index) when that happens.
_VECTOR_OVERFETCH = 20
_VECTOR_MIN_K = 200


class KnowledgeStore(BaseStore):
    """
    Knowledge storage with vector search and label-based retrieval on FalkorDB.

    Shares the FalkorDB graph with EpisodeStore and ArtifactStore.
    Manages Knowledge nodes, Label nodes, and their relationships.

    Node types:
        (:Knowledge) — extracted facts, patterns, insights with embeddings
        (:Label)     — normalized semantic tags, deduplicated via MERGE

    Relationships:
        (:Knowledge)-[:HAS_LABEL]->(:Label)
        (:Knowledge)-[:DERIVED_FROM]->(:Episode)
    """

    # When set, searches use IN $group_ids instead of = $group_id (inherited scope)
    _scope_group_ids: Optional[List[str]] = None

    async def ensure_indexes(self) -> None:
        """Create indexes on Knowledge and Label nodes if they don't exist."""
        index_queries = [
            "CREATE INDEX FOR (k:Knowledge) ON (k.uuid)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.group_id)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.knowledge_type)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.created_at)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.activation_count)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.event_date)",
            "CREATE INDEX FOR (l:Label) ON (l.name)",
        ]
        for q in index_queries:
            try:
                await self._graph.query(q)
            except Exception:
                pass  # Index may already exist

        # Backfill activation_count for Hebbian learning
        try:
            await self._graph.query("""
                MATCH (k:Knowledge)
                WHERE k.activation_count IS NULL
                SET k.activation_count = 0, k.last_activated_at = k.created_at
            """)
        except Exception:
            pass

        # Backfill event_date for existing nodes
        try:
            await self._graph.query("""
                MATCH (k:Knowledge)
                WHERE k.event_date IS NULL
                SET k.event_date = ''
            """)
        except Exception:
            pass

        # Vector (ANN) index — CREATED LAST so the backfill SET queries above
        # finish before the index build starts. Otherwise the massive concurrent
        # AttributeSet_Update (writing all Knowledge nodes) races with the index
        # build in FalkorDB's bio thread → heap corruption → SIGSEGV.
        try:
            await self._graph.query(
                f"CREATE VECTOR INDEX FOR (k:Knowledge) ON (k.embedding) "
                f"OPTIONS {{dimension:{EMBEDDING_DIM}, similarityFunction:'cosine'}}"
            )
            logger.info("KnowledgeStore vector index created on Knowledge.embedding")
        except Exception:
            pass  # Index already exists (or backend lacks vector support → fallback path covers search)

        logger.debug("KnowledgeStore indexes ensured")

    async def store_knowledge(
        self,
        entries: List[Dict[str, Any]],
        source_mission: str,
        mission_status: str,
        source_episode_uuid: str = "",
    ) -> List[str]:
        """
        Store multiple knowledge entries with embeddings, labels, and graph edges.

        Args:
            entries: List of dicts with content, knowledge_type, labels, confidence.
            source_mission: Task summary that produced this knowledge.
            mission_status: "success" or "max_iterations".
            source_episode_uuid: UUID of reflection episode (for DERIVED_FROM edge).

        Returns:
            List of Knowledge UUIDs.
        """
        if not entries:
            return []

        contents = [e.get("content", "") for e in entries]
        embeddings = await self._embed_batch(contents)

        uuids = []
        now = time.time()

        for entry, embedding in zip(entries, embeddings):
            # --- Dedup check: find most similar existing knowledge ---
            similar_uuid = None
            similar_score = 0.0
            if embedding:
                try:
                    dedup_result = await self._graph.ro_query(
                        """MATCH (k:Knowledge)
                        WHERE k.group_id = $group_id
                        WITH k, (2 - vec.cosineDistance(k.embedding, vecf32($query_vec))) / 2 AS score
                        WHERE score >= $threshold
                        RETURN k.uuid AS uuid, score
                        ORDER BY score DESC
                        LIMIT 1""",
                        params={
                            "group_id": self._group_id,
                            "query_vec": embedding,
                            "threshold": 0.75,  # Capture both duplicates and near-similar
                        },
                    )
                    if dedup_result.result_set:
                        similar_uuid = dedup_result.result_set[0][0]
                        similar_score = dedup_result.result_set[0][1]
                except Exception as e:
                    logger.debug("Knowledge similarity check failed (non-fatal): %s", e)

            # If >= 0.90 similar: skip CREATE, reinforce existing with REINFORCES edge
            if similar_uuid and similar_score >= 0.90:
                logger.debug(
                    "Knowledge dedup: skipping '%s...' (similar=%.3f to %s)",
                    entry.get("content", "")[:40],
                    similar_score,
                    similar_uuid[:8],
                )
                if source_episode_uuid:
                    try:
                        await self._graph.query(
                            """MATCH (k:Knowledge {uuid: $k_uuid})
                            MATCH (e:Episode {uuid: $e_uuid})
                            MERGE (k)-[:REINFORCES]->(e)""",
                            params={"k_uuid": similar_uuid, "e_uuid": source_episode_uuid},
                        )
                    except Exception:
                        pass
                uuids.append(similar_uuid)
                continue

            # Otherwise: create new knowledge node
            knowledge_uuid = str(uuid4())
            labels_raw = entry.get("labels", [])
            labels_normalized = [normalize_label(lbl) for lbl in labels_raw if lbl]
            labels_normalized = [lbl for lbl in labels_normalized if lbl]

            await self._graph.query(
                """CREATE (k:Knowledge {
                    uuid: $uuid,
                    group_id: $group_id,
                    content: $content,
                    knowledge_type: $knowledge_type,
                    labels: $labels,
                    confidence: $confidence,
                    source_mission: $source_mission,
                    mission_status: $mission_status,
                    source_episode_uuid: $source_episode_uuid,
                    created_at: $created_at,
                    event_date: $event_date,
                    embedding: vecf32($embedding)
                })""",
                params={
                    "uuid": knowledge_uuid,
                    "group_id": self._group_id,
                    "content": entry.get("content", ""),
                    "knowledge_type": entry.get("knowledge_type", "fact"),
                    "labels": json.dumps(labels_normalized),
                    "confidence": float(entry.get("confidence", 0.8)),
                    "source_mission": source_mission,
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                    "created_at": now,
                    "event_date": entry.get("event_date") or "",
                    "embedding": embedding,
                },
            )

            # Link to similar-but-not-duplicate knowledge with SIMILAR_TO edge
            if similar_uuid and similar_score >= 0.75:
                try:
                    await self._graph.query(
                        """MATCH (new:Knowledge {uuid: $new_uuid})
                        MATCH (similar:Knowledge {uuid: $sim_uuid})
                        MERGE (new)-[:SIMILAR_TO]->(similar)""",
                        params={"new_uuid": knowledge_uuid, "sim_uuid": similar_uuid},
                    )
                except Exception:
                    pass

            for label in labels_normalized:
                await self._graph.query(
                    """MERGE (l:Label {name: $label_name})
                    ON CREATE SET l.created_at = $now
                    WITH l
                    MATCH (k:Knowledge {uuid: $k_uuid})
                    CREATE (k)-[:HAS_LABEL]->(l)""",
                    params={
                        "label_name": label,
                        "now": now,
                        "k_uuid": knowledge_uuid,
                    },
                )

            if source_episode_uuid:
                try:
                    await self._graph.query(
                        """MATCH (k:Knowledge {uuid: $k_uuid})
                        MATCH (e:Episode {uuid: $e_uuid})
                        CREATE (k)-[:DERIVED_FROM]->(e)""",
                        params={
                            "k_uuid": knowledge_uuid,
                            "e_uuid": source_episode_uuid,
                        },
                    )
                except Exception:
                    pass  # Episode may not exist yet

            uuids.append(knowledge_uuid)

        logger.info(f"Stored {len(uuids)} knowledge entries (mission: {source_mission[:40]}...)")
        return uuids

    async def search_by_vector(
        self,
        query: str,
        top_k: int = 10,
        knowledge_type: Optional[str] = None,
        min_score: float = 0.55,
        include_embedding: bool = False,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search on Knowledge embeddings."""
        query_embedding = await self._embed(query)

        type_filter = "AND k.knowledge_type = $knowledge_type" if knowledge_type else ""
        embedding_return = (
            ",\n                k.embedding AS embedding" if include_embedding else ""
        )

        # Determine group filter mode:
        # 1. Inherited scope (ancestor sessions): IN $group_ids
        # 2. Global search (_group_id is None): no group filter
        # 3. Normal: = $group_id
        use_scope = self._scope_group_ids and len(self._scope_group_ids) > 1
        global_search = not use_scope and self._group_id is None
        if use_scope:
            group_filter = "k.group_id IN $group_ids"
        elif global_search:
            group_filter = "true"
        else:
            group_filter = "k.group_id = $group_id"

        # Exclude garbage knowledge types (reflections, metacognition)
        garbage_filter = """
            AND NOT k.knowledge_type IN ['reflection', 'causal_reflection', 'metacognition']
            AND NOT k.content STARTS WITH 'Reflection for:'
            AND NOT k.content STARTS WITH 'Metacognition for:'
        """

        # Columns are identical for both query paths so re-ranking downstream is unaffected.
        return_cols = f"""
                k.uuid AS uuid,
                k.content AS content,
                k.knowledge_type AS knowledge_type,
                k.labels AS labels,
                k.confidence AS confidence,
                k.source_mission AS source_mission,
                k.created_at AS created_at,
                COALESCE(k.event_date, '') AS event_date,
                score,
                COALESCE(k.activation_count, 0) AS activation_count{embedding_return}"""

        # Primary path: ANN via the vector index (O(log n)). queryNodes returns the
        # globally nearest nodes ranked by cosine DISTANCE; (2 - distance) / 2 maps it
        # back to the [0,1] similarity the rest of the code expects. We over-fetch
        # knn_k so enough candidates survive the group/type/garbage post-filter.
        knn_k = max(top_k * _VECTOR_OVERFETCH, _VECTOR_MIN_K)
        # knn_k is inlined as an int literal (server-computed, not user input): some
        # FalkorDB builds require the K arg to queryNodes to be a literal, not a param.
        index_cypher = f"""
            CALL db.idx.vector.queryNodes('Knowledge', 'embedding', {int(knn_k)}, vecf32($query_vec))
            YIELD node AS k, score
            WITH k, (2 - score) / 2 AS score
            WHERE {group_filter} {type_filter} {garbage_filter}
              AND score > $min_score
            RETURN{return_cols}
            ORDER BY score DESC
            LIMIT $top_k
        """

        # Fallback path: brute-force cosine scan. For group-scoped searches the
        # group_id range index bounds this to the group's nodes, so it stays cheap
        # for small/sparse groups where the ANN under-delivers after filtering.
        brute_cypher = f"""
            MATCH (k:Knowledge)
            WHERE {group_filter} {type_filter} {garbage_filter}
            WITH k, (2 - vec.cosineDistance(k.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score > $min_score
            RETURN{return_cols}
            ORDER BY score DESC
            LIMIT $top_k
        """

        params: Dict[str, Any] = {
            "query_vec": query_embedding,
            "min_score": min_score,
            "top_k": top_k * 2,  # Over-fetch for temporal re-ranking
        }
        if use_scope:
            params["group_ids"] = self._scope_group_ids
        elif not global_search:
            params["group_id"] = self._group_id
        if knowledge_type:
            params["knowledge_type"] = knowledge_type

        # Try the index; fall back to brute-force if the index is missing/errors,
        # or if filtered-ANN returned fewer than requested (small group in a large graph).
        result = None
        try:
            result = await self._graph.ro_query(index_cypher, params=params)
            got = len(result.result_set) if result and result.result_set else 0
            if got < min(top_k, params["top_k"]):
                result = await self._graph.ro_query(brute_cypher, params=params)
        except Exception as e:
            logger.warning("Vector index search unavailable (%s); using brute-force scan", e)
            result = await self._graph.ro_query(brute_cypher, params=params)
        rows = self._parse_results(result)

        # Deterministic mode (default): skip the time-varying re-ranking so the
        # same query is reproducible on a stable corpus. Rank on pure vector
        # similarity with a uuid tie-break (the ANN/brute scan can return
        # equal-score rows in an unstable order across runs).
        from ...config import get_search_deterministic

        if get_search_deterministic():
            rows.sort(key=lambda r: (-r.get("score", 0.0), r.get("uuid", "")))
            return rows[:top_k]

        # Multi-dimension scoring: semantic + temporal (+ Hebbian if enabled)
        from ..retrieval.scoring import apply_temporal_score, apply_hebbian_score
        from ...config import (
            get_knowledge_half_life,
            get_knowledge_alpha,
            get_hebbian_enabled,
            get_hebbian_beta_knowledge,
        )

        if get_hebbian_enabled():
            rows = apply_hebbian_score(
                rows,
                beta=get_hebbian_beta_knowledge(),
                alpha=get_knowledge_alpha(),
                half_life_hours=get_knowledge_half_life(),
            )
        else:
            rows = apply_temporal_score(
                rows,
                alpha=get_knowledge_alpha(),
                half_life_hours=get_knowledge_half_life(),
            )
        return rows[:top_k]

    async def search_by_labels(
        self,
        labels: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Label-based search via HAS_LABEL graph edges. Ranks by match count."""
        normalized = [normalize_label(lbl) for lbl in labels if lbl]
        if not normalized:
            return []

        cypher = """
            MATCH (k:Knowledge)-[:HAS_LABEL]->(l:Label)
            WHERE k.group_id = $group_id AND l.name IN $labels
            WITH k, count(l) AS label_matches
            RETURN
                k.uuid AS uuid,
                k.content AS content,
                k.knowledge_type AS knowledge_type,
                k.labels AS labels,
                k.confidence AS confidence,
                k.source_mission AS source_mission,
                k.created_at AS created_at,
                COALESCE(k.event_date, '') AS event_date,
                toFloat(label_matches) / $total_labels AS score
            ORDER BY label_matches DESC, k.created_at DESC
            LIMIT $top_k
        """

        result = await self._graph.ro_query(
            cypher,
            params={
                "group_id": self._group_id,
                "labels": normalized,
                "total_labels": float(len(normalized)),
                "top_k": top_k,
            },
        )
        return self._parse_results(result)

    async def search_by_date_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        knowledge_type: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search knowledge by event_date range. Dates are ISO 8601 (YYYY-MM-DD)."""
        filters = ["k.group_id = $group_id", "k.event_date <> ''"]
        params: Dict[str, Any] = {"group_id": self._group_id, "top_k": top_k}

        if start_date:
            filters.append("k.event_date >= $start_date")
            params["start_date"] = start_date
        if end_date:
            filters.append("k.event_date <= $end_date")
            params["end_date"] = end_date
        if knowledge_type:
            filters.append("k.knowledge_type = $knowledge_type")
            params["knowledge_type"] = knowledge_type

        where_clause = " AND ".join(filters)

        cypher = f"""
            MATCH (k:Knowledge)
            WHERE {where_clause}
            RETURN
                k.uuid AS uuid,
                k.content AS content,
                k.knowledge_type AS knowledge_type,
                k.labels AS labels,
                k.confidence AS confidence,
                k.source_mission AS source_mission,
                k.created_at AS created_at,
                COALESCE(k.event_date, '') AS event_date,
                1.0 AS score
            ORDER BY k.event_date DESC
            LIMIT $top_k
        """

        result = await self._graph.ro_query(cypher, params=params)
        return self._parse_results(result)

    async def search_hybrid(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.50,
        label_boost: float = 0.15,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_embedding: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: vector similarity + label match boosting.

        1. Vector search → top_k * 2 candidates with scores
        2. If labels, query label matches for candidates
        3. final_score = vector_score + (label_boost * label_match_ratio)
        4. Re-rank by final_score, return top_k
        """
        candidates = await self.search_by_vector(
            query, top_k=top_k * 2, min_score=min_score, include_embedding=include_embedding
        )

        if not candidates:
            return []

        if not labels:
            return candidates[:top_k]

        normalized_labels = [normalize_label(lbl) for lbl in labels if lbl]
        if not normalized_labels:
            return candidates[:top_k]

        candidate_uuids = [c["uuid"] for c in candidates]

        try:
            label_result = await self._graph.ro_query(
                """MATCH (k:Knowledge)-[:HAS_LABEL]->(l:Label)
                WHERE k.uuid IN $uuids AND l.name IN $labels
                RETURN k.uuid AS uuid, count(l) AS label_matches""",
                params={
                    "uuids": candidate_uuids,
                    "labels": normalized_labels,
                },
            )

            label_map = {}
            if label_result.result_set:
                for row in label_result.result_set:
                    label_map[row[0]] = row[1]
        except Exception:
            label_map = {}

        total_labels = len(normalized_labels)
        for candidate in candidates:
            match_count = label_map.get(candidate["uuid"], 0)
            label_ratio = match_count / total_labels if total_labels > 0 else 0
            candidate["score"] = candidate["score"] + (label_boost * label_ratio)

        # Optional temporal filter (non-temporal knowledge passes through)
        if start_date or end_date:

            def _in_date_range(c):
                ed = c.get("event_date", "")
                if not ed:
                    return True
                if start_date and ed < start_date:
                    return False
                if end_date and ed > end_date:
                    return False
                return True

            candidates = [c for c in candidates if _in_date_range(c)]

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]
