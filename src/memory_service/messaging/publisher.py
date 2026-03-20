"""Event publishers — fire-and-forget publishing to NATS JetStream."""

import logging

from .schemas import CurationCompletedEvent, EpisodeStoredEvent

logger = logging.getLogger(__name__)


def _sanitize_group_id(group_id: str) -> str:
    """Replace dots/spaces with hyphens for NATS subject token safety."""
    return group_id.replace(".", "-").replace(" ", "-")


class EpisodeEventPublisher:
    """Publishes episode lifecycle events to NATS JetStream."""

    def __init__(self, nats_client):
        self._nats = nats_client

    async def episode_stored(
        self,
        episode_uuid: str,
        group_id: str,
        episode_type: str = "raw",
        content_length: int = 0,
        consolidation_status: str = "pending",
        created_at: float = None,
        source: str = "episode_store",
    ) -> None:
        """Publish memory.episode.stored.<group_id> event."""
        subject = f"memory.episode.stored.{_sanitize_group_id(group_id)}"
        event = EpisodeStoredEvent(
            episode_uuid=episode_uuid,
            group_id=group_id,
            episode_type=episode_type,
            content_length=content_length,
            consolidation_status=consolidation_status,
            **({"created_at": created_at} if created_at is not None else {}),
            source=source,
        )
        try:
            ack = await self._nats.jetstream.publish(
                subject,
                event.model_dump_json().encode(),
                headers={"Nats-Msg-Id": episode_uuid},
            )
            logger.debug(f"Published {subject}: uuid={episode_uuid[:8]}, seq={ack.seq}")
        except Exception as e:
            logger.warning(f"Failed to publish episode event: {e}")

    async def curation_completed(
        self,
        group_id: str,
        result: dict,
        duration_ms: float,
    ) -> None:
        """Publish memory.curation.completed.<group_id> event."""
        subject = f"memory.curation.completed.{_sanitize_group_id(group_id)}"
        event = CurationCompletedEvent(
            group_id=group_id,
            episodes_consolidated=result.get("episodes_consolidated", 0),
            knowledge_count=result.get("knowledge_count", 0),
            artifact_count=result.get("artifact_count", 0),
            compressed_uuid=result.get("compressed_uuid", ""),
            reflection_uuid=result.get("reflection_uuid", ""),
            duration_ms=duration_ms,
        )
        try:
            await self._nats.jetstream.publish(subject, event.model_dump_json().encode())
            logger.debug(f"Published curation completed for {group_id}")
        except Exception as e:
            logger.warning(f"Failed to publish curation completed: {e}")
