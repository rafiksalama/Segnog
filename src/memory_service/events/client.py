"""NATS client — manages connection, JetStream, and stream creation."""

import logging
from typing import Optional

import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig

logger = logging.getLogger(__name__)


class NatsClient:
    """NATS client with JetStream support for the memory service."""

    def __init__(self, url: str = "nats://localhost:4222"):
        self._url = url
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None

    async def connect(self) -> None:
        """Connect to NATS and set up JetStream streams."""
        self._nc = await nats.connect(
            self._url,
            reconnect_time_wait=2,
            max_reconnect_attempts=-1,
            error_cb=self._error_cb,
            disconnected_cb=self._disconnected_cb,
            reconnected_cb=self._reconnected_cb,
        )
        self._js = self._nc.jetstream()
        await self._ensure_streams()
        logger.info(f"NATS connected: {self._url}")

    async def _ensure_streams(self) -> None:
        """Create or update the MEMORY_EVENTS stream."""
        config = StreamConfig(
            name="MEMORY_EVENTS",
            subjects=[
                "memory.episode.stored.*",
                "memory.curation.completed.*",
                "memory.rem.sweep.trigger",
                "memory.rem.sweep.completed",
            ],
            max_age=86400,  # 24h
            max_msgs=100_000,
            storage="file",
            num_replicas=1,
        )
        try:
            await self._js.add_stream(config)
            logger.info("Created MEMORY_EVENTS stream")
        except nats.js.errors.BadRequestError:
            await self._js.update_stream(config)
            logger.debug("Updated MEMORY_EVENTS stream")

    @property
    def jetstream(self) -> JetStreamContext:
        if not self._js:
            raise RuntimeError("NATS not connected")
        return self._js

    @property
    def nc(self):
        return self._nc

    async def close(self) -> None:
        if self._nc and not self._nc.is_closed:
            await self._nc.drain()
            logger.info("NATS connection drained and closed")

    async def _error_cb(self, e):
        logger.error(f"NATS error: {e}")

    async def _disconnected_cb(self):
        logger.warning("NATS disconnected")

    async def _reconnected_cb(self):
        logger.info("NATS reconnected")
