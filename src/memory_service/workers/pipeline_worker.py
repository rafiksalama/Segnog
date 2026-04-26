"""Generic NATS JetStream pipeline workers.

* :class:`PipelineWorker` — base: FIFO, one-job-at-a-time.
* :class:`SyncWorker` — runs handler, sends reply (request-reply).
* :class:`AsyncWorker` — runs handler, acks (fire-and-forget).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict

import nats.js.api

logger = logging.getLogger(__name__)

# The NATS ``nats.NATS`` request() timeout is in seconds.
_DEFAULT_ACK_WAIT = 600  # 10 min — ontology pipeline can be slow
_STREAM_NAME = "PIPELINES"
_STREAM_SUBJECTS = ["memory.pipeline.>*"]


class PipelineWorker:
    """Base NATS JetStream worker — FIFO, one job at a time.

    Subclasses override :meth:`_process` to control whether a reply
    is sent back to the caller.
    """

    def __init__(
        self,
        name: str,
        nats_client,  # NatsClient from messaging.client
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
        subject: str,
        stream: str = _STREAM_NAME,
        max_ack_pending: int = 1,
        ack_wait: int = _DEFAULT_ACK_WAIT,
    ) -> None:
        self._name = name
        self._nats_client = nats_client
        self._handler = handler
        self._subject = subject
        self._stream = stream
        self._max_ack_pending = max_ack_pending
        self._ack_wait = ack_wait
        self._running = False
        self._sub = None

    async def run(self) -> None:
        """Main loop — ensure stream, subscribe, process messages."""
        js = self._nats_client.jetstream

        # Ensure the PIPELINES stream exists
        try:
            await js.add_stream(
                config=nats.js.api.StreamConfig(
                    name=self._stream,
                    subjects=["memory.pipeline.>"],
                    max_age=86400,
                    max_msgs=100_000,
                    storage="file",
                )
            )
            logger.info("PipelineWorker: created stream '%s'", self._stream)
        except Exception:
            pass  # stream already exists

        self._sub = await js.pull_subscribe(
            self._subject,
            durable=f"{self._name}-worker",
            config=nats.js.api.ConsumerConfig(
                ack_wait=self._ack_wait,
                max_deliver=2,
                max_ack_pending=self._max_ack_pending,
            ),
        )

        self._running = True
        logger.info("PipelineWorker[%s] started (subject=%s)", self._name, self._subject)

        try:
            while self._running:
                try:
                    msgs = await self._sub.fetch(batch=1, timeout=5)
                    for msg in msgs:
                        await self._process(msg)
                except nats.errors.TimeoutError:
                    pass
                except Exception as e:
                    if self._running:
                        logger.error("PipelineWorker[%s] fetch error: %s", self._name, e)
                        import asyncio

                        await asyncio.sleep(1)
        except asyncio.CancelledError:
            self._running = False
            logger.info("PipelineWorker[%s] stopped", self._name)

    async def _process(self, msg) -> None:
        """Override in subclasses. Called for each message."""
        raise NotImplementedError

    async def stop(self) -> None:
        self._running = False


class SyncWorker(PipelineWorker):
    """Runs handler, sends result back via reply subject.

    Used when the caller needs the result before proceeding
    (e.g. reflection -> knowledge dependency).
    """

    async def _process(self, msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            result = await self._handler(payload)

            # Send reply to caller (NATS request-reply)
            if msg.reply:
                await self._nats_client.nc.publish(
                    msg.reply,
                    json.dumps(result).encode(),
                )
            await msg.ack()
            logger.debug("SyncWorker[%s]: processed", self._name)
        except Exception as e:
            logger.error("SyncWorker[%s]: handler failed: %s", self._name, e, exc_info=True)
            try:
                await msg.nak()
            except Exception:
                pass


class AsyncWorker(PipelineWorker):
    """Runs handler, acks. No reply. Fire-and-forget.

    Used for independent pipeline stages (artifacts, causals, ontology).
    """

    async def _process(self, msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            await self._handler(payload)
            await msg.ack()
            logger.debug("AsyncWorker[%s]: processed", self._name)
        except Exception as e:
            logger.error(
                "AsyncWorker[%s]: handler failed: %s",
                self._name,
                e,
                exc_info=True,
            )
            try:
                await msg.nak()
            except Exception:
                pass
