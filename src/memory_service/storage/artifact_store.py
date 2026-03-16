"""
Artifact Store

Persistent artifact registry on FalkorDB with vector + label hybrid search.
Shares the same FalkorDB graph as EpisodeStore and KnowledgeStore.

Tracks tangible outputs from agent missions: files saved, content downloaded,
reports generated, datasets compiled, code written.

Write path: extract entries → batch embed (~200ms) → store Artifact + Label nodes → done.
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


class ArtifactStore(BaseStore):
    """
    Artifact storage with vector search and label-based retrieval on FalkorDB.

    Shares the FalkorDB graph with EpisodeStore and KnowledgeStore.
    Manages Artifact nodes, Label nodes, and their relationships.

    Node types:
        (:Artifact) — registered outputs with embeddings, types, paths
        (:Label)    — normalized semantic tags, deduplicated via MERGE (shared)

    Relationships:
        (:Artifact)-[:HAS_LABEL]->(:Label)
        (:Artifact)-[:DERIVED_FROM]->(:Episode)
    """

    async def ensure_indexes(self) -> None:
        """Create indexes on Artifact nodes if they don't exist."""
        index_queries = [
            "CREATE INDEX FOR (a:Artifact) ON (a.uuid)",
            "CREATE INDEX FOR (a:Artifact) ON (a.group_id)",
            "CREATE INDEX FOR (a:Artifact) ON (a.artifact_type)",
            "CREATE INDEX FOR (a:Artifact) ON (a.created_at)",
        ]
        for q in index_queries:
            try:
                await self._graph.query(q)
            except Exception:
                pass  # Index may already exist
        logger.debug("ArtifactStore indexes ensured")

    async def store_artifacts(
        self,
        entries: List[Dict[str, Any]],
        source_mission: str,
        mission_status: str,
        source_episode_uuid: str = "",
    ) -> List[str]:
        """
        Store multiple artifact entries with embeddings, labels, and graph edges.

        Args:
            entries: List of dicts with name, artifact_type, path, description, labels.
            source_mission: Task summary that produced these artifacts.
            mission_status: "success" or "max_iterations".
            source_episode_uuid: UUID of reflection episode (for DERIVED_FROM edge).

        Returns:
            List of Artifact UUIDs.
        """
        if not entries:
            return []

        descriptions = [e.get("description", "") for e in entries]
        embeddings = await self._embed_batch(descriptions)

        uuids = []
        now = time.time()

        for entry, embedding in zip(entries, embeddings):
            artifact_uuid = str(uuid4())
            labels_raw = entry.get("labels", [])
            labels_normalized = [normalize_label(lbl) for lbl in labels_raw if lbl]
            labels_normalized = [lbl for lbl in labels_normalized if lbl]

            await self._graph.query(
                """CREATE (a:Artifact {
                    uuid: $uuid,
                    group_id: $group_id,
                    name: $name,
                    artifact_type: $artifact_type,
                    path: $path,
                    description: $description,
                    labels: $labels,
                    source_mission: $source_mission,
                    mission_status: $mission_status,
                    source_episode_uuid: $source_episode_uuid,
                    created_at: $created_at,
                    embedding: vecf32($embedding)
                })""",
                params={
                    "uuid": artifact_uuid,
                    "group_id": self._group_id,
                    "name": entry.get("name", "")[:200],
                    "artifact_type": entry.get("artifact_type", "file"),
                    "path": entry.get("path", "")[:500],
                    "description": entry.get("description", "")[:500],
                    "labels": json.dumps(labels_normalized),
                    "source_mission": source_mission[:200],
                    "mission_status": mission_status,
                    "source_episode_uuid": source_episode_uuid,
                    "created_at": now,
                    "embedding": embedding,
                },
            )

            for label in labels_normalized:
                await self._graph.query(
                    """MERGE (l:Label {name: $label_name})
                    ON CREATE SET l.created_at = $now
                    WITH l
                    MATCH (a:Artifact {uuid: $a_uuid})
                    CREATE (a)-[:HAS_LABEL]->(l)""",
                    params={
                        "label_name": label,
                        "now": now,
                        "a_uuid": artifact_uuid,
                    },
                )

            if source_episode_uuid:
                try:
                    await self._graph.query(
                        """MATCH (a:Artifact {uuid: $a_uuid})
                        MATCH (e:Episode {uuid: $e_uuid})
                        CREATE (a)-[:DERIVED_FROM]->(e)""",
                        params={
                            "a_uuid": artifact_uuid,
                            "e_uuid": source_episode_uuid,
                        },
                    )
                except Exception:
                    pass  # Episode may not exist yet

            uuids.append(artifact_uuid)

        logger.info(
            f"Stored {len(uuids)} artifact entries "
            f"(mission: {source_mission[:40]}...)"
        )
        return uuids

    async def get_by_uuid(self, artifact_uuid: str) -> Optional[Dict[str, Any]]:
        """Fetch a single artifact by UUID. Returns dict or None."""
        result = await self._graph.ro_query(
            """MATCH (a:Artifact {uuid: $uuid, group_id: $group_id})
            RETURN
                a.uuid AS uuid,
                a.name AS name,
                a.artifact_type AS artifact_type,
                a.path AS path,
                a.description AS description,
                a.labels AS labels,
                a.source_mission AS source_mission,
                a.mission_status AS mission_status,
                a.created_at AS created_at""",
            params={"uuid": artifact_uuid, "group_id": self._group_id},
        )
        rows = self._parse_results(result)
        return rows[0] if rows else None

    async def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent artifacts ordered by creation time descending."""
        result = await self._graph.ro_query(
            """MATCH (a:Artifact)
            WHERE a.group_id = $group_id
            RETURN
                a.uuid AS uuid,
                a.name AS name,
                a.artifact_type AS artifact_type,
                a.path AS path,
                a.description AS description,
                a.labels AS labels,
                a.source_mission AS source_mission,
                a.mission_status AS mission_status,
                a.created_at AS created_at
            ORDER BY a.created_at DESC
            LIMIT $limit""",
            params={"group_id": self._group_id, "limit": limit},
        )
        return self._parse_results(result)

    async def delete_by_uuid(self, artifact_uuid: str) -> bool:
        """Delete an artifact and all its edges. Returns True if it existed."""
        existing = await self.get_by_uuid(artifact_uuid)
        if not existing:
            return False
        await self._graph.query(
            "MATCH (a:Artifact {uuid: $uuid, group_id: $group_id}) DETACH DELETE a",
            params={"uuid": artifact_uuid, "group_id": self._group_id},
        )
        return True

    async def search_by_vector(
        self,
        query: str,
        top_k: int = 10,
        artifact_type: Optional[str] = None,
        min_score: float = 0.50,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search on Artifact embeddings."""
        query_embedding = await self._embed(query)

        type_filter = (
            "AND a.artifact_type = $artifact_type" if artifact_type else ""
        )

        cypher = f"""
            MATCH (a:Artifact)
            WHERE a.group_id = $group_id {type_filter}
            WITH a, (2 - vec.cosineDistance(a.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score > $min_score
            RETURN
                a.uuid AS uuid,
                a.name AS name,
                a.artifact_type AS artifact_type,
                a.path AS path,
                a.description AS description,
                a.labels AS labels,
                a.source_mission AS source_mission,
                a.created_at AS created_at,
                score
            ORDER BY score DESC
            LIMIT $top_k
        """

        params = {
            "group_id": self._group_id,
            "query_vec": query_embedding,
            "min_score": min_score,
            "top_k": top_k,
        }
        if artifact_type:
            params["artifact_type"] = artifact_type

        result = await self._graph.ro_query(cypher, params=params)
        return self._parse_results(result)

    async def search_hybrid(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.45,
        label_boost: float = 0.15,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: vector similarity + label match boosting.

        1. Vector search → top_k * 2 candidates with scores
        2. If labels, query label matches for candidates
        3. final_score = vector_score + (label_boost * label_match_ratio)
        4. Re-rank by final_score, return top_k
        """
        candidates = await self.search_by_vector(
            query, top_k=top_k * 2, min_score=min_score
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
                """MATCH (a:Artifact)-[:HAS_LABEL]->(l:Label)
                WHERE a.uuid IN $uuids AND l.name IN $labels
                RETURN a.uuid AS uuid, count(l) AS label_matches""",
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

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

