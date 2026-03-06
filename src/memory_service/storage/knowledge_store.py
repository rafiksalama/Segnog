"""
Knowledge Store

Persistent knowledge graph on FalkorDB with vector + label hybrid search.
Shares the same FalkorDB graph as EpisodeStore and ArtifactStore.

Write path: extract entries → batch embed (~200ms) → store Knowledge + Label nodes → done.
Search path: embed query (~200ms) → hybrid vector + label search (~50ms) → done.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def normalize_label(raw: str) -> str:
    """
    Normalize a semantic label for consistent storage and retrieval.

    "Web Search" → "web-search"
    "web_search" → "web-search"
    "Machine Learning!" → "machine-learning"
    """
    label = raw.lower().strip()
    label = label.replace("_", "-").replace(" ", "-")
    label = re.sub(r"[^a-z0-9\-]", "", label)
    label = re.sub(r"-+", "-", label).strip("-")
    return label


class KnowledgeStore:
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

    def __init__(
        self,
        graph,           # falkordb.asyncio.AsyncGraph
        openai_client,   # openai.AsyncOpenAI
        embedding_model: str,
        group_id: str = "default",
    ):
        self._graph = graph
        self._client = openai_client
        self._model = embedding_model
        self._group_id = group_id

    async def ensure_indexes(self) -> None:
        """Create indexes on Knowledge and Label nodes if they don't exist."""
        index_queries = [
            "CREATE INDEX FOR (k:Knowledge) ON (k.uuid)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.group_id)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.knowledge_type)",
            "CREATE INDEX FOR (k:Knowledge) ON (k.created_at)",
            "CREATE INDEX FOR (l:Label) ON (l.name)",
        ]
        for q in index_queries:
            try:
                await self._graph.query(q)
            except Exception:
                pass  # Index may already exist
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
            knowledge_uuid = str(uuid4())
            labels_raw = entry.get("labels", [])
            labels_normalized = [normalize_label(l) for l in labels_raw if l]
            labels_normalized = [l for l in labels_normalized if l]

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
                    embedding: vecf32($embedding)
                })""",
                params={
                    "uuid": knowledge_uuid,
                    "group_id": self._group_id,
                    "content": entry.get("content", ""),
                    "knowledge_type": entry.get("knowledge_type", "fact"),
                    "labels": json.dumps(labels_normalized),
                    "confidence": float(entry.get("confidence", 0.8)),
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

        logger.info(
            f"Stored {len(uuids)} knowledge entries "
            f"(mission: {source_mission[:40]}...)"
        )
        return uuids

    async def search_by_vector(
        self,
        query: str,
        top_k: int = 10,
        knowledge_type: Optional[str] = None,
        min_score: float = 0.55,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search on Knowledge embeddings."""
        query_embedding = await self._embed(query)

        type_filter = (
            "AND k.knowledge_type = $knowledge_type" if knowledge_type else ""
        )

        cypher = f"""
            MATCH (k:Knowledge)
            WHERE k.group_id = $group_id {type_filter}
            WITH k, (2 - vec.cosineDistance(k.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score > $min_score
            RETURN
                k.uuid AS uuid,
                k.content AS content,
                k.knowledge_type AS knowledge_type,
                k.labels AS labels,
                k.confidence AS confidence,
                k.source_mission AS source_mission,
                k.created_at AS created_at,
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
        if knowledge_type:
            params["knowledge_type"] = knowledge_type

        result = await self._graph.ro_query(cypher, params=params)
        return self._parse_results(result)

    async def search_by_labels(
        self,
        labels: List[str],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Label-based search via HAS_LABEL graph edges. Ranks by match count."""
        normalized = [normalize_label(l) for l in labels if l]
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

    async def search_hybrid(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        top_k: int = 10,
        min_score: float = 0.50,
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

        normalized_labels = [normalize_label(l) for l in labels if l]
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

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_k]

    def _parse_results(self, result) -> List[Dict[str, Any]]:
        """Parse FalkorDB QueryResult into list of dicts."""
        if not result.result_set:
            return []

        columns = [
            h[1] if isinstance(h, (list, tuple)) else h for h in result.header
        ]
        rows = []
        for row in result.result_set:
            record = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if col == "labels" and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                record[col] = val
            rows.append(record)

        return rows

    async def _embed(self, text: str) -> List[float]:
        """Generate embedding via OpenAI-compatible API."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embedding for multiple knowledge entries."""
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]
