"""
Episode Store

Fast episode storage with vector search on FalkorDB.
Supports sequential linking (FOLLOWS edges) and graph expansion.

Write path: embed text (~200ms) → store node (~50ms) → auto-link (~10ms) → done.
Search path: embed query (~200ms) → cosine similarity (~50ms) → optional expand (~20ms) → done.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)


def _parse_datetime(dt_string: str) -> Optional[float]:
    """
    Best-effort parse of human-readable datetime strings.
    Handles formats like "1:56 pm on 8 May, 2023".
    Returns epoch float or None.
    """
    from dateutil import parser as dateutil_parser
    try:
        dt = dateutil_parser.parse(dt_string, fuzzy=True)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def normalize_entity_name(raw: str) -> str:
    """
    Normalize an entity name for consistent storage and deduplication.

    "Julia Horrocks" → "julia-horrocks"
    "Dr. Smith" → "dr-smith"
    """
    name = raw.lower().strip()
    name = name.replace("_", "-").replace(" ", "-")
    name = re.sub(r"[^a-z0-9\-]", "", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name


class EpisodeStore:
    """
    Episode storage with vector search on FalkorDB.

    Episodes are nodes with content, metadata, embedding, and episode_type.
    Sequential episodes within a group are connected via FOLLOWS edges.

    Episode types:
        - "raw": Mission execution traces
        - "reflection": Curator-produced summaries
        - "compressed": Archived summaries of old raw episodes
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
        """Create indexes on Episode nodes if they don't exist."""
        for field in (
            "uuid", "group_id", "episode_type",
            "created_at", "created_at_iso", "consolidation_status",
        ):
            try:
                await self._graph.query(
                    f"CREATE INDEX FOR (e:Episode) ON (e.{field})"
                )
            except Exception:
                pass  # Index may already exist

        # Entity indexes
        for field in ("name", "entity_type"):
            try:
                await self._graph.query(
                    f"CREATE INDEX FOR (ent:Entity) ON (ent.{field})"
                )
            except Exception:
                pass

        # Backfill consolidation_status on existing episodes
        try:
            await self._graph.query("""
                MATCH (e:Episode)
                WHERE e.consolidation_status IS NULL AND e.episode_type = 'raw'
                SET e.consolidation_status = 'pending'
            """)
            await self._graph.query("""
                MATCH (e:Episode)
                WHERE e.consolidation_status IS NULL AND e.episode_type <> 'raw'
                SET e.consolidation_status = 'consolidated'
            """)
        except Exception:
            pass  # May fail on empty graph

        logger.debug("EpisodeStore indexes ensured")

    async def store_episode(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        episode_type: str = "raw",
        auto_link: bool = True,
    ) -> str:
        """
        Store an episode with its embedding in FalkorDB.

        If metadata contains a 'date_time' field, it is parsed and used as
        the episode's created_at timestamp (native temporal context).

        If auto_link is True, creates a FOLLOWS edge from the most recent
        prior episode in the same group.

        Returns:
            UUID of the stored episode.
        """
        embedding = await self._embed(content)
        return await self._store_with_embedding(
            content, embedding, metadata, episode_type, auto_link
        )

    async def _store_with_embedding(
        self,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        episode_type: str = "raw",
        auto_link: bool = True,
    ) -> str:
        """Store an episode using a pre-computed embedding vector."""
        episode_uuid = str(uuid4())
        metadata_json = json.dumps(metadata or {})

        # Use metadata.date_time as timestamp if available (native temporal context)
        created_at = time.time()
        if metadata and metadata.get("date_time"):
            parsed_time = _parse_datetime(metadata["date_time"])
            if parsed_time:
                created_at = parsed_time

        created_at_iso = datetime.fromtimestamp(
            created_at, tz=timezone.utc
        ).isoformat()

        consolidation_status = (
            "consolidated" if episode_type in ("reflection", "compressed", "narrative")
            else "pending"
        )

        await self._graph.query(
            """CREATE (e:Episode {
                uuid: $uuid,
                group_id: $group_id,
                content: $content,
                episode_type: $episode_type,
                consolidation_status: $consolidation_status,
                metadata: $metadata,
                created_at: $created_at,
                created_at_iso: $created_at_iso,
                embedding: vecf32($embedding)
            })""",
            params={
                "uuid": episode_uuid,
                "group_id": self._group_id,
                "content": content,
                "episode_type": episode_type,
                "consolidation_status": consolidation_status,
                "metadata": metadata_json,
                "created_at": created_at,
                "created_at_iso": created_at_iso,
                "embedding": embedding,
            },
        )

        if auto_link:
            await self._auto_link_to_predecessor(episode_uuid, created_at)

        logger.debug(
            f"Stored episode {episode_uuid[:8]} "
            f"(type={episode_type}, len={len(content)})"
        )
        return episode_uuid

    # ── Linking ────────────────────────────────────────────────────────

    async def link_episodes(
        self,
        from_uuid: str,
        to_uuid: str,
        edge_type: str = "FOLLOWS",
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Create a directed edge between two Episode nodes.

        Args:
            from_uuid: Source episode UUID (earlier in time).
            to_uuid: Target episode UUID (later in time).
            edge_type: Relationship type. Default "FOLLOWS".
            properties: Optional edge properties (e.g., time_delta_seconds).

        Returns:
            True if the edge was created.
        """
        props_clause = ""
        params: Dict[str, Any] = {"from_uuid": from_uuid, "to_uuid": to_uuid}

        if properties:
            prop_pairs = []
            for key, value in properties.items():
                param_name = f"prop_{key}"
                prop_pairs.append(f"{key}: ${param_name}")
                params[param_name] = value
            props_clause = " {" + ", ".join(prop_pairs) + "}"

        cypher = f"""
            MATCH (a:Episode {{uuid: $from_uuid}})
            MATCH (b:Episode {{uuid: $to_uuid}})
            CREATE (a)-[r:{edge_type}{props_clause}]->(b)
            RETURN count(r) AS created
        """

        try:
            result = await self._graph.query(cypher, params=params)
            created = result.result_set[0][0] if result.result_set else 0
            if created:
                logger.debug(
                    f"Linked episodes {from_uuid[:8]} -[{edge_type}]-> {to_uuid[:8]}"
                )
            return created > 0
        except Exception as e:
            logger.warning(f"Failed to link episodes: {e}")
            return False

    async def get_adjacent_episodes(
        self,
        uuid: str,
        hops: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get episodes connected via FOLLOWS or DERIVED_FROM edges within N hops.

        Traverses both temporal (FOLLOWS) and provenance (DERIVED_FROM) chains
        to support multi-hop reasoning.

        Returns:
            List of adjacent episode dicts (without embedding),
            ordered by created_at.
        """
        cypher = f"""
            MATCH (center:Episode {{uuid: $uuid}})
            OPTIONAL MATCH (center)-[:FOLLOWS*1..{hops}]->(fwd_f:Episode)
            OPTIONAL MATCH (bwd_f:Episode)-[:FOLLOWS*1..{hops}]->(center)
            OPTIONAL MATCH (center)-[:DERIVED_FROM*1..{hops}]->(fwd_d:Episode)
            OPTIONAL MATCH (bwd_d:Episode)-[:DERIVED_FROM*1..{hops}]->(center)
            WITH collect(DISTINCT fwd_f) + collect(DISTINCT bwd_f)
               + collect(DISTINCT fwd_d) + collect(DISTINCT bwd_d) AS neighbors
            UNWIND neighbors AS neighbor
            WHERE neighbor IS NOT NULL
            RETURN DISTINCT
                neighbor.uuid AS uuid,
                neighbor.content AS content,
                neighbor.episode_type AS episode_type,
                neighbor.metadata AS metadata,
                neighbor.created_at AS created_at,
                neighbor.created_at_iso AS created_at_iso
            ORDER BY created_at ASC
        """
        try:
            result = await self._graph.ro_query(cypher, params={"uuid": uuid})
        except Exception as e:
            logger.warning(f"Graph expansion failed: {e}")
            return []

        if not result.result_set:
            return []

        columns = [h[1] if isinstance(h, (list, tuple)) else h for h in result.header]
        rows = []
        for row in result.result_set:
            record = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if col == "metadata" and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                record[col] = val
            rows.append(record)
        return rows

    async def _auto_link_to_predecessor(
        self,
        new_uuid: str,
        new_created_at: float,
    ) -> None:
        """Find the most recent prior episode in the same group_id and link it."""
        cypher = """
            MATCH (prev:Episode)
            WHERE prev.group_id = $group_id
              AND prev.uuid <> $new_uuid
              AND prev.created_at <= $new_created_at
            RETURN prev.uuid AS prev_uuid, prev.created_at AS prev_created_at
            ORDER BY prev.created_at DESC
            LIMIT 1
        """
        try:
            result = await self._graph.ro_query(cypher, params={
                "group_id": self._group_id,
                "new_uuid": new_uuid,
                "new_created_at": new_created_at,
            })
            if result.result_set:
                prev_uuid = result.result_set[0][0]
                prev_created_at = result.result_set[0][1]
                time_delta = new_created_at - prev_created_at
                await self.link_episodes(
                    from_uuid=prev_uuid,
                    to_uuid=new_uuid,
                    edge_type="FOLLOWS",
                    properties={"time_delta_seconds": time_delta},
                )
        except Exception as e:
            logger.warning(f"Auto-link failed (non-critical): {e}")

    # ── Search ─────────────────────────────────────────────────────────

    async def search_episodes(
        self,
        query: str,
        top_k: int = 25,
        episode_type: Optional[str] = None,
        min_score: float = 0.55,
        expand_adjacent: bool = False,
        expansion_hops: int = 1,
        after_time: Optional[float] = None,
        before_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Vector similarity search on stored episodes.

        Args:
            query: Search query text.
            top_k: Maximum results to return.
            episode_type: Filter by episode type.
            min_score: Minimum cosine similarity score.
            expand_adjacent: If True, include FOLLOWS-connected neighbors.
            expansion_hops: Number of hops for graph expansion.
            after_time: Only include episodes after this epoch time.
            before_time: Only include episodes before this epoch time.

        Returns:
            List of dicts with uuid, content, episode_type, metadata,
            created_at, created_at_iso, score.
        """
        query_embedding = await self._embed(query)
        return await self._search_with_embedding(
            query_embedding, top_k, episode_type, min_score,
            expand_adjacent, expansion_hops, after_time, before_time,
        )

    async def _search_with_embedding(
        self,
        embedding: List[float],
        top_k: int = 25,
        episode_type: Optional[str] = None,
        min_score: float = 0.55,
        expand_adjacent: bool = False,
        expansion_hops: int = 1,
        after_time: Optional[float] = None,
        before_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search using a pre-computed embedding vector."""
        type_filter = "AND e.episode_type = $episode_type" if episode_type else ""
        time_filter = ""
        if after_time is not None:
            time_filter += " AND e.created_at > $after_time"
        if before_time is not None:
            time_filter += " AND e.created_at < $before_time"

        cypher = f"""
            MATCH (e:Episode)
            WHERE e.group_id = $group_id {type_filter} {time_filter}
            WITH e, (2 - vec.cosineDistance(e.embedding, vecf32($query_vec))) / 2 AS score
            WHERE score > $min_score
            RETURN
                e.uuid AS uuid,
                e.content AS content,
                e.episode_type AS episode_type,
                e.metadata AS metadata,
                e.created_at AS created_at,
                e.created_at_iso AS created_at_iso,
                score
            ORDER BY score DESC
            LIMIT $top_k
        """

        params: Dict[str, Any] = {
            "group_id": self._group_id,
            "query_vec": embedding,
            "min_score": min_score,
            "top_k": top_k,
        }
        if episode_type:
            params["episode_type"] = episode_type
        if after_time is not None:
            params["after_time"] = after_time
        if before_time is not None:
            params["before_time"] = before_time

        result = await self._graph.ro_query(cypher, params=params)

        if not result.result_set:
            return []

        columns = [h[1] if isinstance(h, (list, tuple)) else h for h in result.header]
        rows = []
        for row in result.result_set:
            record = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if col == "metadata" and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                record[col] = val
            rows.append(record)

        if not expand_adjacent:
            logger.debug(f"Search returned {len(rows)} episodes")
            return rows

        # Graph expansion: for each hit, fetch adjacent episodes
        seen_uuids = {r["uuid"] for r in rows}
        expanded = []
        for row in rows:
            neighbors = await self.get_adjacent_episodes(
                uuid=row["uuid"], hops=expansion_hops
            )
            for neighbor in neighbors:
                if neighbor["uuid"] not in seen_uuids:
                    seen_uuids.add(neighbor["uuid"])
                    neighbor["score"] = row["score"] * 0.9  # Discount factor
                    neighbor["_source"] = "graph_expansion"
                    expanded.append(neighbor)

        combined = rows + expanded
        combined.sort(key=lambda x: x.get("score", 0), reverse=True)
        logger.debug(
            f"Search returned {len(rows)} + {len(expanded)} expanded "
            f"= {len(combined)} episodes"
        )
        return combined

    # ── Consolidation ──────────────────────────────────────────────────

    async def mark_episodes_consolidated(self, uuids: List[str]) -> int:
        """Bulk-mark episodes as consolidated. Returns count updated."""
        if not uuids:
            return 0
        cypher = """
            UNWIND $uuids AS uid
            MATCH (e:Episode {uuid: uid})
            SET e.consolidation_status = 'consolidated'
            RETURN count(e) AS updated
        """
        result = await self._graph.query(cypher, params={"uuids": uuids})
        count = result.result_set[0][0] if result.result_set else 0
        logger.debug(f"Marked {count} episodes as consolidated")
        return count

    async def compress_raw_episodes(
        self,
        group_id: str,
        source_uuids: List[str],
        summary_content: str,
    ) -> str:
        """
        Create a compressed Episode summarising source episodes.
        Links back to sources via DERIVED_FROM edges.
        Returns UUID of the compressed episode.
        """
        embedding = await self._embed(summary_content)
        compressed_uuid = str(uuid4())
        now = time.time()
        created_at_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        await self._graph.query(
            """CREATE (e:Episode {
                uuid: $uuid,
                group_id: $group_id,
                content: $content,
                episode_type: 'compressed',
                consolidation_status: 'consolidated',
                metadata: $metadata,
                created_at: $created_at,
                created_at_iso: $created_at_iso,
                embedding: vecf32($embedding)
            })""",
            params={
                "uuid": compressed_uuid,
                "group_id": group_id,
                "content": summary_content,
                "metadata": json.dumps({
                    "source": "rem_compression",
                    "source_count": len(source_uuids),
                }),
                "created_at": now,
                "created_at_iso": created_at_iso,
                "embedding": embedding,
            },
        )

        # Link compressed episode to each source
        for src_uuid in source_uuids:
            try:
                await self._graph.query(
                    """MATCH (c:Episode {uuid: $c_uuid})
                       MATCH (s:Episode {uuid: $s_uuid})
                       CREATE (c)-[:DERIVED_FROM]->(s)""",
                    params={"c_uuid": compressed_uuid, "s_uuid": src_uuid},
                )
            except Exception as e:
                logger.warning(f"DERIVED_FROM edge failed for {src_uuid[:8]}: {e}")

        logger.info(
            f"Compressed {len(source_uuids)} episodes into {compressed_uuid[:8]}"
        )
        return compressed_uuid

    # ── Entity Resolution ───────────────────────────────────────────

    async def link_entities(
        self,
        episode_uuid: str,
        entities: List[Dict[str, Any]],
    ) -> int:
        """
        Link entities to an episode via MENTIONS edges.

        Creates Entity nodes (MERGE for dedup) and MENTIONS edges.

        Args:
            episode_uuid: UUID of the episode to link entities to.
            entities: List of dicts with name and entity_type.

        Returns:
            Number of entities linked.
        """
        if not entities:
            return 0

        now = time.time()
        linked = 0
        for entity in entities:
            name = entity.get("name", "").strip()
            entity_type = entity.get("entity_type", "unknown")
            if not name:
                continue

            normalized = normalize_entity_name(name)
            if not normalized:
                continue

            try:
                await self._graph.query(
                    """MERGE (ent:Entity {name: $normalized})
                    ON CREATE SET ent.display_name = $display_name,
                                  ent.entity_type = $entity_type,
                                  ent.created_at = $now
                    WITH ent
                    MATCH (e:Episode {uuid: $episode_uuid})
                    CREATE (e)-[:MENTIONS]->(ent)""",
                    params={
                        "normalized": normalized,
                        "display_name": name,
                        "entity_type": entity_type,
                        "now": now,
                        "episode_uuid": episode_uuid,
                    },
                )
                linked += 1
            except Exception as e:
                logger.warning(f"Entity link failed for '{name}': {e}")

        if linked:
            logger.debug(f"Linked {linked} entities to episode {episode_uuid[:8]}")
        return linked

    async def search_by_entities(
        self,
        entity_names: List[str],
        top_k: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        Find episodes that mention given entities.

        Args:
            entity_names: List of entity names to search for.
            top_k: Maximum results.

        Returns:
            List of episode dicts with mention_count as score.
        """
        normalized = [normalize_entity_name(n) for n in entity_names if n]
        normalized = [n for n in normalized if n]
        if not normalized:
            return []

        cypher = """
            MATCH (e:Episode)-[:MENTIONS]->(ent:Entity)
            WHERE e.group_id = $group_id AND ent.name IN $entity_names
            WITH e, count(DISTINCT ent) AS mention_count
            RETURN
                e.uuid AS uuid,
                e.content AS content,
                e.episode_type AS episode_type,
                e.metadata AS metadata,
                e.created_at AS created_at,
                e.created_at_iso AS created_at_iso,
                toFloat(mention_count) / $total_entities AS score
            ORDER BY mention_count DESC, e.created_at DESC
            LIMIT $top_k
        """

        try:
            result = await self._graph.ro_query(
                cypher,
                params={
                    "group_id": self._group_id,
                    "entity_names": normalized,
                    "total_entities": float(len(normalized)),
                    "top_k": top_k,
                },
            )
        except Exception as e:
            logger.warning(f"Entity search failed: {e}")
            return []

        if not result.result_set:
            return []

        columns = [h[1] if isinstance(h, (list, tuple)) else h for h in result.header]
        rows = []
        for row in result.result_set:
            record = {}
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else None
                if col == "metadata" and isinstance(val, str):
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


async def create_episode_store(
    falkordb_url: str = None,
    graph_name: str = None,
    embedding_model: str = None,
    embedding_base_url: str = None,
    embedding_api_key: str = None,
    group_id: str = "default",
) -> EpisodeStore:
    """
    Create an EpisodeStore connected to FalkorDB with embeddings.

    All parameters fall back to service config if not provided.

    Returns:
        Initialized EpisodeStore with indexes created.
    """
    import os
    from falkordb.asyncio import FalkorDB
    from openai import AsyncOpenAI

    from ..config import (
        get_falkordb_url,
        get_falkordb_graph_name,
        get_embedding_model,
        get_embedding_base_url,
        get_embedding_api_key,
    )

    falkordb_url = falkordb_url or get_falkordb_url()
    graph_name = graph_name or get_falkordb_graph_name()
    embedding_model = embedding_model or get_embedding_model()
    embedding_base_url = embedding_base_url or get_embedding_base_url()
    embedding_api_key = embedding_api_key or get_embedding_api_key()

    parsed = urlparse(falkordb_url)

    db = FalkorDB(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6380,
        password=parsed.password,
    )
    graph = db.select_graph(graph_name)

    if not embedding_api_key:
        raise RuntimeError("Embedding API key not configured")

    openai_client = AsyncOpenAI(
        api_key=embedding_api_key,
        base_url=embedding_base_url,
    )

    store = EpisodeStore(
        graph=graph,
        openai_client=openai_client,
        embedding_model=embedding_model,
        group_id=group_id,
    )
    await store.ensure_indexes()

    logger.info(
        f"EpisodeStore initialized: FalkorDB at "
        f"{parsed.hostname or 'localhost'}:{parsed.port or 6380}, "
        f"graph={graph_name}"
    )
    return store
