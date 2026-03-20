"""REM Sweep Worker — timer-triggered full sweep via NATS.

Replaces the asyncio.sleep(60) polling loop. A timer coroutine publishes
sweep triggers to NATS, and this worker subscribes to execute them.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class REMSweepPublisher:
    """Publishes periodic sweep triggers to NATS."""

    def __init__(self, nats_client, interval_seconds: int = 60):
        self._nats = nats_client
        self._interval = interval_seconds
        self._running = False

    async def run(self) -> None:
        """Periodically publish sweep triggers."""
        self._running = True
        logger.info(f"REM sweep timer started (interval={self._interval}s)")
        try:
            while self._running:
                await asyncio.sleep(self._interval)
                try:
                    payload = {
                        "trigger_type": "timer",
                        "interval_seconds": self._interval,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await self._nats.jetstream.publish(
                        "memory.rem.sweep.trigger",
                        json.dumps(payload).encode(),
                    )
                    logger.debug("Published REM sweep trigger")
                except Exception as e:
                    logger.warning(f"Failed to publish sweep trigger: {e}")
        except asyncio.CancelledError:
            self._running = False
            logger.info("REM sweep timer stopped")


class REMSweepWorker:
    """Subscribes to sweep triggers and runs full REM sweep.

    Sweep includes:
    - Find orphan groups (groups with pending episodes missed by CurationWorker)
    - Run curation for orphan groups
    - Hebbian decay
    """

    def __init__(
        self,
        nats_client,
        handler,
        episode_store,
        batch_size: int = 5,
        min_episodes: int = 1,
        ontology_store=None,
        dragonfly=None,
    ):
        self._nats = nats_client
        self._handler = handler
        self._episode_store = episode_store
        self._batch_size = batch_size
        self._min_episodes = min_episodes
        self._ontology_store = ontology_store
        self._dragonfly = dragonfly
        self._running = False

    async def run(self) -> None:
        """Subscribe to sweep triggers and process them."""
        self._running = True
        js = self._nats.jetstream

        sub = await js.pull_subscribe(
            "memory.rem.sweep.trigger",
            durable="rem-sweep-worker",
        )

        logger.info("REMSweepWorker started")

        try:
            while self._running:
                try:
                    msgs = await sub.fetch(batch=1, timeout=10)
                    for msg in msgs:
                        try:
                            await self._run_sweep()
                            await msg.ack()
                        except Exception as e:
                            logger.error(f"Sweep failed: {e}", exc_info=True)
                            try:
                                await msg.nak()
                            except Exception:
                                pass
                except Exception:
                    pass  # Timeout, loop back
        except asyncio.CancelledError:
            self._running = False
            logger.info("REMSweepWorker stopped")

    async def _run_sweep(self) -> None:
        """Full sweep: reuse existing REMWorker logic."""
        import time as _time
        from .rem_worker import REMWorker

        temp_worker = REMWorker(
            handler=self._handler,
            episode_store=self._episode_store,
            interval_seconds=0,
            batch_size=self._batch_size,
            min_episodes=self._min_episodes,
            ontology_store=self._ontology_store,
        )
        t0 = _time.perf_counter()
        await temp_worker._run_cycle()
        logger.info("REM sweep completed")

        # Record sweep latency (fire-and-forget, runs in parallel)
        if self._dragonfly:
            dur = (_time.perf_counter() - t0) * 1000
            asyncio.create_task(self._dragonfly.record_latency("BG:sweep/cycle", dur))
