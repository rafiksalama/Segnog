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
                max_connections=20,
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

    async def get_events_for_group(
        self,
        group_id: str,
        count: int = 100,
        event_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent events across all workflow streams for a given group_id.

        Scans all ``events:{group_id}:*`` keys so the caller doesn't need to
        know which workflow_id was used when the events were logged.
        """
        if not self.connected:
            return []
        try:
            keys = await self._client.keys(f"events:{group_id}:*")
            if not keys:
                return []

            all_events: List[Dict[str, Any]] = []
            per_key = max(count, 20)
            for key in keys:
                entries = await self._client.xrevrange(key, "+", "-", count=per_key)
                for stream_id, data in entries:
                    all_events.append(self._parse_event(stream_id, data))

            all_events.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
            if event_types:
                all_events = [e for e in all_events if e.get("type") in event_types]
            return all_events[:count]
        except Exception as e:
            logger.error("get_events_for_group(%s) failed: %s", group_id, e)
            return []

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
                self.stream_key,
                "+",
                "-",
                count=count,
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
            value = json.dumps(
                {
                    "content": content,
                    "embedding": embedding,
                    "metadata": metadata,
                    "source_type": source_type,
                    "created_at": time.time(),
                }
            )
            async with self._client.pipeline(transaction=False) as pipe:
                pipe.hset(key, entry_uuid, value)
                pipe.expire(key, self._session_ttl)
                await pipe.execute()
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
                results.append(
                    {
                        "uuid": entry_uuid,
                        "content": entry["content"],
                        "metadata": entry.get("metadata", {}),
                        "source_type": entry.get("source_type", "local"),
                        "created_at": entry.get("created_at", 0),
                        "score": score,
                    }
                )

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
    # Latency Telemetry (sliding window, per endpoint)
    # =========================================================================

    async def record_latency(self, endpoint: str, duration_ms: float) -> None:
        """Append one timestamped latency sample (non-blocking — call via create_task).

        Each sample is stored as "unix_ts:ms" in a Redis list capped at 200 entries.
        A companion SET tracks all known endpoint names for efficient enumeration.
        """
        if not self.connected:
            return
        try:
            sample = f"{time.time():.3f}:{round(duration_ms, 2)}"
            key = f"latency:{endpoint}"
            async with self._client.pipeline(transaction=False) as pipe:
                pipe.sadd("latency:endpoints", endpoint)
                pipe.lpush(key, sample)
                pipe.ltrim(key, 0, 199)  # keep last 200 samples
                pipe.expire(key, 86400)  # 24 h TTL
                await pipe.execute()
        except Exception as e:
            logger.debug("record_latency failed (non-critical): %s", e)

    async def get_latency_stats(self) -> list:
        """Return per-endpoint stats + recent timestamped samples for realtime charts.

        Each entry: {endpoint, count, mean, p50, p95, p99, max, samples: [{ts, ms}]}
        where samples is the last 60 entries ordered oldest-first.
        """
        if not self.connected:
            return []
        try:
            endpoints = await self._client.smembers("latency:endpoints")
        except Exception:
            return []

        results = []
        for ep in endpoints:
            ep_str = ep.decode() if isinstance(ep, bytes) else ep
            try:
                raw = await self._client.lrange(f"latency:{ep_str}", 0, -1)
            except Exception:
                continue
            if not raw:
                continue

            # Parse "ts:ms" pairs (format written by record_latency)
            parsed = []
            for entry in raw:
                entry = entry.decode() if isinstance(entry, bytes) else entry
                try:
                    ts_str, ms_str = entry.rsplit(":", 1)
                    parsed.append((float(ts_str), float(ms_str)))
                except ValueError:
                    pass

            if not parsed:
                continue

            ms_vals = sorted(p[1] for p in parsed)
            n = len(ms_vals)

            # Last 60 samples ordered oldest-first for the time-series chart
            recent_raw = sorted(parsed, key=lambda x: x[0])[-60:]
            samples = [{"ts": round(ts, 3), "ms": ms} for ts, ms in recent_raw]

            results.append(
                {
                    "endpoint": ep_str,
                    "count": n,
                    "mean": round(sum(ms_vals) / n, 1),
                    "p50": round(ms_vals[max(0, int(n * 0.50) - 1)], 1),
                    "p95": round(ms_vals[max(0, int(n * 0.95) - 1)], 1),
                    "p99": round(ms_vals[max(0, int(n * 0.99) - 1)], 1),
                    "max": round(ms_vals[-1], 1),
                    "samples": samples,
                }
            )

        return sorted(results, key=lambda x: x["count"], reverse=True)

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
