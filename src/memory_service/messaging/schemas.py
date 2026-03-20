"""Pydantic schemas for NATS event payloads.

Provides typed models for every event published to / consumed from NATS JetStream.
Using Pydantic for serialisation gives field-level validation, clear contracts between
producer and consumer, and IDE-friendly auto-complete.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EpisodeStoredEvent(BaseModel):
    """Payload for ``memory.episode.stored.<group_id>``."""

    episode_uuid: str
    group_id: str
    episode_type: str = "raw"
    content_length: int = 0
    consolidation_status: str = "pending"
    created_at: float = Field(default_factory=time.time)
    source: str = "episode_store"
    timestamp: str = Field(default_factory=_now_iso)


class CurationCompletedEvent(BaseModel):
    """Payload for ``memory.curation.completed.<group_id>``."""

    group_id: str
    episodes_consolidated: int = 0
    knowledge_count: int = 0
    artifact_count: int = 0
    compressed_uuid: str = ""
    reflection_uuid: str = ""
    duration_ms: float = 0.0
    timestamp: str = Field(default_factory=_now_iso)
