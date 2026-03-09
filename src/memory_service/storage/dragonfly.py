"""
DragonflyDB Client

Simple Redis/DragonflyDB client using redis.asyncio.
Provides event logging (Redis Streams) and state persistence (Redis Hashes).
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DragonflyClient:
    """
    DragonflyDB client using redis.asyncio.

    Provides:
        - Event logging via Redis Streams (log_event, get_events, get_recent_events)
        - State persistence via Redis Hashes (hset, hgetall)
        - Scope management (group_id, workflow_id)

    Usage:
        client = DragonflyClient(redis_url="redis://localhost:6381")
        await client.connect()
        event_id = await client.log_event("observation", {"content": "test"})
        events = await client.get_recent_events(count=10)
        await client.close()
    """

    def __init__(
        self,
        redis_url: str = None,
        group_id: str = "default",
        workflow_id: str = "default",
        session_ttl: int = 3600,
    ):
        self.redis_url = redis_url or os.getenv("DRAGONFLY_URL", "redis://localhost:6381")
        self.group_id = group_id
        self.workflow_id = workflow_id
        self._session_ttl = session_ttl
        self._client = None
        self._connected = False

    async def connect(self) -> bool:
        """Connect to DragonflyDB."""
        if self._connected:
            return True

        try:
            import redis.asyncio as redis

            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            self._connected = True
            logger.info(f"Connected to DragonflyDB at {self.redis_url}")
            return True

        except Exception as e:
            logger.error(f"DragonflyDB connection error: {e}")
            return False

    async def close(self) -> None:
        """Close the connection."""
        if self._client:
            await self._client.close()
            self._connected = False
            logger.info("DragonflyDB disconnected")

    @property
    def connected(self) -> bool:
        return self._connected and self._client is not None

    @property
    def stream_key(self) -> str:
        """Redis stream key for current scope."""
        return f"events:{self.group_id}:{self.workflow_id}"

    # =========================================================================
    # Event Operations (Redis Streams)
    # =========================================================================

    async def log_event(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> Optional[str]:
        """
        Log an event to the Redis Stream.

        Returns:
            Event ID if successful, None otherwise.
        """
        if not self.connected:
            logger.warning("Not connected, cannot log event")
            return None

        try:
            event_id = str(uuid.uuid4())
            timestamp = time.time()

            event_data = {
                "event_id": event_id,
                "type": event_type,
                "timestamp": str(timestamp),
                "group_id": self.group_id,
                "workflow_id": self.workflow_id,
                "data": json.dumps(data),
            }

            stream_id = await self._client.xadd(self.stream_key, event_data)
            logger.debug(f"Logged event {event_type}: {stream_id}")
            return event_id

        except Exception as e:
            logger.error(f"Failed to log event: {e}")
            return None

    async def get_recent_events(
        self,
        count: int = 100,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent events from the stream (newest first)."""
        if not self.connected:
            return []

        try:
            entries = await self._client.xrevrange(
                self.stream_key, "+", "-", count=count,
            )

            events = []
            for stream_id, data in entries:
                event = self._parse_event(stream_id, data)
                if event_type is None or event.get("type") == event_type:
                    events.append(event)

            return events

        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []

    def _parse_event(self, stream_id: str, data: Dict[str, str]) -> Dict[str, Any]:
        """Parse event data from Redis stream entry."""
        event = {
            "stream_id": stream_id,
            "event_id": data.get("event_id", ""),
            "type": data.get("type", ""),
            "timestamp": float(data.get("timestamp", 0)),
            "group_id": data.get("group_id", ""),
            "workflow_id": data.get("workflow_id", ""),
        }

        data_str = data.get("data", "{}")
        try:
            event["data"] = json.loads(data_str)
        except json.JSONDecodeError:
            event["data"] = {"raw": data_str}

        return event

    # =========================================================================
    # Hash Operations (Redis Hashes)
    # =========================================================================

    async def hset(self, key: str, mapping: Dict[str, Any]) -> None:
        """Set hash fields in DragonflyDB."""
        if not self.connected:
            logger.warning("Not connected, cannot hset")
            return

        try:
            serialized = {}
            for k, v in mapping.items():
                if isinstance(v, str):
                    serialized[k] = v
                else:
                    serialized[k] = json.dumps(v)

            await self._client.hset(key, mapping=serialized)
            logger.debug(f"HSET {key} with {len(mapping)} fields")

        except Exception as e:
            logger.error(f"HSET failed: {e}")

    async def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields from DragonflyDB."""
        if not self.connected:
            return {}

        try:
            result = await self._client.hgetall(key)

            parsed = {}
            for k, v in (result or {}).items():
                try:
                    parsed[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed[k] = v

            return parsed

        except Exception as e:
            logger.error(f"HGETALL failed: {e}")
            return {}

    # =========================================================================
    # Session Operations (Redis Hashes with embeddings)
    # =========================================================================

    async def session_add(
        self,
        session_id: str,
        entry_uuid: str,
        content: str,
        embedding: List[float],
        metadata: dict,
        source_type: str = "local",
    ) -> None:
        """Add an entry to a session hash with its embedding."""
        if not self.connected:
            return
        try:
            key = f"session:{session_id}"
            value = json.dumps({
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
                "source_type": source_type,
                "created_at": time.time(),
            })
            await self._client.hset(key, entry_uuid, value)
            await self._client.expire(key, self._session_ttl)
        except Exception as e:
            logger.error(f"session_add failed: {e}")

    async def session_search(
        self,
        session_id: str,
        query_embedding: List[float],
        top_k: int = 25,
        min_score: float = 0.40,
    ) -> List[Dict[str, Any]]:
        """Search session entries by cosine similarity (computed in Python).

        Returns raw cosine similarity results sorted by score descending.
        Caller is responsible for multi-dimensional scoring.
        """
        import numpy as np

        entries = await self.session_get_all(session_id)
        if not entries:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        results = []
        for entry_uuid, entry in entries.items():
            emb_data = entry.get("embedding")
            if not emb_data:
                continue
            emb = np.array(emb_data, dtype=np.float32)
            emb_norm = np.linalg.norm(emb)
            if emb_norm == 0:
                continue
            score = float(np.dot(query_vec, emb) / (query_norm * emb_norm))
            if score >= min_score:
                results.append({
                    "uuid": entry_uuid,
                    "content": entry["content"],
                    "metadata": entry.get("metadata", {}),
                    "source_type": entry.get("source_type", "local"),
                    "created_at": entry.get("created_at", 0),
                    "score": score,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    async def session_get_all(self, session_id: str) -> Dict[str, Any]:
        """Get all entries in a session, parsed from JSON."""
        if not self.connected:
            return {}
        try:
            key = f"session:{session_id}"
            raw = await self._client.hgetall(key)
            entries = {}
            for entry_uuid, val in (raw or {}).items():
                try:
                    entries[entry_uuid] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            return entries
        except Exception as e:
            logger.error(f"session_get_all failed: {e}")
            return {}

    async def session_has(self, session_id: str, entry_uuid: str) -> bool:
        """Check if an entry already exists in the session (for dedup)."""
        if not self.connected:
            return False
        try:
            key = f"session:{session_id}"
            return await self._client.hexists(key, entry_uuid)
        except Exception:
            return False

    async def session_count(self, session_id: str) -> int:
        """Get the number of entries in a session."""
        if not self.connected:
            return 0
        try:
            key = f"session:{session_id}"
            return await self._client.hlen(key)
        except Exception:
            return 0

    # =========================================================================
    # Scope & Utility
    # =========================================================================

    def set_scope(self, group_id: str = None, workflow_id: str = None) -> None:
        """Update the group/workflow scope for events."""
        if group_id:
            self.group_id = group_id
        if workflow_id:
            self.workflow_id = workflow_id



async def create_dragonfly_client(
    url: str = None,
    group_id: str = "default",
    workflow_id: str = "default",
) -> DragonflyClient:
    """
    Create and connect a DragonflyClient.

    Raises:
        RuntimeError: If connection fails.
    """
    client = DragonflyClient(
        redis_url=url,
        group_id=group_id,
        workflow_id=workflow_id,
    )

    if not await client.connect():
        raise RuntimeError(f"Failed to connect to DragonflyDB at {client.redis_url}")

    return client
