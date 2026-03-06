"""
Short-Term Memory

DragonflyDB-backed key-value store with special routing:
    - "event:*"  keys → Redis Stream (via DragonflyClient)
    - "state:*"  keys → Redis Hash  (via DragonflyClient)
    - other keys → in-memory dict

This is a general-purpose short-term memory — no framework-specific DTOs.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Event type constants (framework-agnostic)
EVENT_TYPES = {
    "llm_request", "llm_response",
    "tool_call", "tool_result",
    "action", "observation",
    "error", "state_update",
}


class ShortTermMemory:
    """
    Short-term memory store backed by DragonflyDB.

    Routes by key prefix:
        - "event:*" → logged to DragonflyDB Redis Stream
        - "state:*" → stored in DragonflyDB Redis Hash ("state")
        - other → simple in-memory dict
    """

    def __init__(self, dragonfly_client):
        """
        Args:
            dragonfly_client: DragonflyClient instance (must be connected).
        """
        if dragonfly_client is None:
            raise ValueError("Dragonfly client is required")
        self._dragonfly = dragonfly_client
        self._memory: Dict[str, Any] = {}

    async def save(self, key: str, value: Any) -> None:
        """Save a value. Routing depends on key prefix."""
        if key.startswith("event:"):
            await self._log_event(key, value)
        elif key.startswith("state:"):
            await self._save_state(key, value)
        else:
            self._memory[key] = value

    async def get(self, key: str) -> Optional[Any]:
        """
        Get a value. Special keys:
            - "recent_events"          → last 10 events
            - "recent_events:N"        → last N events
            - "recent_events:N:type"   → last N events of given type
            - "state:*"                → from DragonflyDB hash
            - other                    → from in-memory dict
        """
        if key.startswith("recent_events"):
            return await self._get_recent_events(key)
        elif key.startswith("state:"):
            return await self._get_state(key)
        else:
            return self._memory.get(key)

    async def delete(self, key: str) -> None:
        self._memory.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._memory

    async def list_keys(self, pattern: str = "*") -> List[str]:
        if pattern == "*":
            return list(self._memory.keys())

        if pattern.startswith("*") and pattern.endswith("*"):
            substring = pattern.strip("*")
            return [k for k in self._memory.keys() if substring in k]

        if pattern.endswith("*"):
            prefix = pattern.rstrip("*")
            return [k for k in self._memory.keys() if k.startswith(prefix)]

        if pattern.startswith("*"):
            suffix = pattern.lstrip("*")
            return [k for k in self._memory.keys() if k.endswith(suffix)]

        return [k for k in self._memory.keys() if k == pattern]

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _log_event(self, key: str, value: Any) -> None:
        """Log event to DragonflyDB stream."""
        parts = key.split(":")
        event_type_str = parts[1] if len(parts) > 1 else "observation"

        if isinstance(value, dict):
            data = value.copy()
        else:
            data = {"content": value}

        event_id = await self._dragonfly.log_event(event_type_str, data)
        logger.debug(f"Logged event: {event_type_str} -> {event_id}")

    async def _save_state(self, key: str, value: Any) -> None:
        """Save state to DragonflyDB hash."""
        if isinstance(value, (dict, list)):
            serialized = json.dumps(value)
        else:
            serialized = str(value)

        await self._dragonfly.hset("state", {
            key: json.dumps({
                "value": serialized,
                "updated_at": time.time(),
            })
        })
        logger.debug(f"Saved state: {key}")

    async def _get_state(self, key: str) -> Optional[Any]:
        """Get state from DragonflyDB hash."""
        data = await self._dragonfly.hgetall("state")
        if key in data:
            try:
                state_data = json.loads(data[key]) if isinstance(data[key], str) else data[key]
                value = state_data.get("value") if isinstance(state_data, dict) else data[key]
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            except (json.JSONDecodeError, AttributeError):
                return data[key]
        return None

    async def _get_recent_events(self, key: str) -> List[Dict[str, Any]]:
        """Get recent events from DragonflyDB stream."""
        parts = key.split(":")
        count = int(parts[1]) if len(parts) > 1 else 10
        event_type = parts[2] if len(parts) > 2 else None

        events = await self._dragonfly.get_recent_events(
            count=count,
            event_type=event_type,
        )

        return [self._parse_event(e) for e in events]

    def _parse_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse event data into structured format."""
        event_type_str = data.get("type", "observation")

        return {
            "event_id": data.get("event_id", ""),
            "type": event_type_str,
            "content": data.get("content", data.get("data", data)),
            "timestamp": data.get("timestamp"),
            "metadata": {
                k: v for k, v in data.items()
                if k not in ("event_id", "type", "content", "timestamp", "data")
            },
        }
