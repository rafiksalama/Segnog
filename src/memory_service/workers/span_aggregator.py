"""SpanAggregator — background task that processes timing span events.

Reads ``timing:spans`` DragonflyDB stream, correlates start↔end pairs by
``span_id``, computes ``duration_ms``, and feeds each completed span into
the existing ``record_latency`` time-series under the key
``{operation}:{step}`` so it appears in the ``/ui/latency`` dashboard
automatically.

Architecture
------------
::

    observe / background_hydrate
        │  SpanTracer.start("embed")  →  create_task → xadd "phase=start"
        │  ... do work ...
        │  SpanTracer.end(span_id, "embed", ts_start)  →  xadd "phase=end"
        │
        └─► SpanAggregator (runs in parallel)
               │  xread timing:spans  (non-blocking poll, 200 ms interval)
               │  match start↔end by span_id
               └► dragonfly.record_latency("{operation}:{step}", duration_ms)

The aggregator never blocks the event loop — it uses a short ``asyncio.sleep``
between polls and calls ``xread`` without blocking (``count`` only, no
``block`` parameter) to stay cooperative.
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_TIMING_STREAM = "timing:spans"
_POLL_INTERVAL = 0.2  # seconds between polls when stream is empty
_STALE_SPAN_TTL = 60.0  # seconds before an unmatched start is discarded
_BATCH_SIZE = 200  # events read per poll


async def run_span_aggregator(dragonfly) -> None:
    """Run forever — call via ``asyncio.create_task`` from app lifespan.

    Args:
        dragonfly: Connected :class:`~memory_service.storage.short_term.dragonfly.DragonflyClient`
    """
    pending: dict[str, dict] = {}  # span_id → {operation, step, ts_start}
    last_id = "0-0"  # stream cursor (exclusive lower bound)

    logger.info("SpanAggregator started — reading %s", _TIMING_STREAM)

    while True:
        try:
            if not dragonfly.connected:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            # Non-blocking read: fetch up to _BATCH_SIZE new messages
            raw = await dragonfly._client.xread(
                {_TIMING_STREAM: last_id},
                count=_BATCH_SIZE,
            )

            if not raw:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            for _stream, messages in raw:
                for msg_id, fields in messages:
                    last_id = msg_id if isinstance(msg_id, str) else msg_id.decode()
                    _process_span_event(fields, pending, dragonfly)

            # Prune stale unmatched starts (prevents unbounded memory growth)
            now = time.time()
            stale = [
                sid for sid, info in pending.items() if now - info["ts_start"] > _STALE_SPAN_TTL
            ]
            for sid in stale:
                logger.debug("SpanAggregator: pruning stale span %s.%s", sid, pending[sid]["step"])
                del pending[sid]

        except asyncio.CancelledError:
            logger.info("SpanAggregator cancelled")
            return
        except Exception as exc:
            logger.warning("SpanAggregator error: %s", exc)
            await asyncio.sleep(_POLL_INTERVAL)


def _process_span_event(fields: dict, pending: dict, dragonfly) -> None:
    """Match a single stream event against pending starts; fire record_latency on match."""

    # Redis stream values are bytes or str depending on decode_responses setting
    def _get(key: str) -> str:
        v = fields.get(key, b"")
        return v.decode() if isinstance(v, bytes) else str(v)

    phase = _get("phase")
    span_id = _get("span_id")
    if not span_id:
        return

    if phase == "start":
        try:
            pending[span_id] = {
                "operation": _get("operation"),
                "step": _get("step"),
                "session_id": _get("session_id"),
                "ts_start": float(_get("ts") or 0),
            }
        except (ValueError, TypeError) as exc:
            logger.debug("SpanAggregator: bad start event %s: %s", span_id, exc)

    elif phase == "end":
        info = pending.pop(span_id, None)
        if info is None:
            return  # start event not seen (e.g. aggregator restarted mid-span)
        try:
            ts_start = float(_get("ts_start") or info["ts_start"])
            ts_end = float(_get("ts") or time.time())
            duration_ms = (ts_end - ts_start) * 1000.0
            latency_key = f"{info['operation']}:{info['step']}"
            # Fire-and-forget — avoid blocking the aggregator loop
            asyncio.create_task(
                dragonfly.record_latency(latency_key, duration_ms),
                name=f"span_record:{span_id}",
            )
        except (ValueError, TypeError) as exc:
            logger.debug("SpanAggregator: bad end event %s: %s", span_id, exc)
