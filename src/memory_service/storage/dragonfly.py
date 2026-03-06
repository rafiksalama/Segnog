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
    ):
        self.redis_url = redis_url or os.getenv("DRAGONFLY_URL", "redis://localhost:6381")
        self.group_id = group_id
        self.workflow_id = workflow_id
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

    async def get_events(
        self,
        count: int = 100,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get events from the stream (oldest first)."""
        if not self.connected:
            return []

        try:
            entries = await self._client.xrange(
                self.stream_key, "-", "+", count=count,
            )

            events = []
            for stream_id, data in entries:
                event = self._parse_event(stream_id, data)
                if event_type is None or event.get("type") == event_type:
                    events.append(event)

            return events

        except Exception as e:
            logger.error(f"Failed to get events: {e}")
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
    # Scope & Utility
    # =========================================================================

    def set_scope(self, group_id: str = None, workflow_id: str = None) -> None:
        """Update the group/workflow scope for events."""
        if group_id:
            self.group_id = group_id
        if workflow_id:
            self.workflow_id = workflow_id

    async def get_stream_length(self) -> int:
        """Get the number of events in the current stream."""
        if not self.connected:
            return 0
        try:
            return await self._client.xlen(self.stream_key)
        except Exception:
            return 0

    async def clear_events(self) -> bool:
        """Clear all events in the current stream."""
        if not self.connected:
            return False
        try:
            await self._client.delete(self.stream_key)
            return True
        except Exception as e:
            logger.error(f"Clear events failed: {e}")
            return False


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
