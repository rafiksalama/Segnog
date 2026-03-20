"""Structured span-based timing system.

Each operation emits a pair of fire-and-forget events:
  - ``timing_span_start`` – emitted when a step begins
  - ``timing_span_end``   – emitted when a step ends (with ts_start for delta)

A parallel :class:`SpanAggregator` background task reads those events from a
dedicated DragonflyDB stream, computes ``duration_ms = ts_end - ts_start``, and
feeds the result into the existing ``record_latency`` time-series so it appears
in the ``/ui/latency`` dashboard automatically.

Event schema
------------
Both events share these fields (stored as Redis stream field/value strings):

    span_id   : str   – random 12-char hex, correlates start↔end
    operation : str   – high-level operation name, e.g. "observe"
    step      : str   – sub-step name, e.g. "embed", "session_add"
    session_id: str   – session context (may be empty)
    phase     : str   – "start" | "end"
    ts        : float – unix timestamp (seconds, float)

``timing_span_end`` additionally carries:

    ts_start  : float – copied from the matching start event
    error     : "1"   – present only when the step raised an exception
"""

import asyncio
import logging
import time
from uuid import uuid4

logger = logging.getLogger(__name__)

# DragonflyDB stream key – kept separate from user event streams
_TIMING_STREAM = "timing:spans"
# Max entries retained in the stream (capped on write)
_STREAM_MAXLEN = 20_000


class SpanTracer:
    """Emit start/end span events to DragonflyDB (fire-and-forget).

    Usage::

        tracer = SpanTracer(dragonfly, "observe", session_id)

        span_id, t0 = tracer.start("embed")
        embedding = await episode_store._embed(content)
        tracer.end(span_id, "embed", t0)

    Both :meth:`start` and :meth:`end` return immediately — all I/O is
    dispatched as ``asyncio.create_task`` so they never block the caller.
    """

    def __init__(self, dragonfly, operation: str, session_id: str = ""):
        self._dragonfly = dragonfly
        self._operation = operation
        self._session_id = session_id

    def start(self, step: str) -> tuple[str, float]:
        """Emit a ``timing_span_start`` event.

        Returns ``(span_id, ts_start)`` — pass both to :meth:`end`.
        """
        span_id = uuid4().hex[:12]
        ts = time.time()
        asyncio.create_task(
            self._emit_span("start", span_id, step, ts),
            name=f"span_start:{span_id}",
        )
        return span_id, ts

    def end(self, span_id: str, step: str, ts_start: float, error: bool = False) -> None:
        """Emit a ``timing_span_end`` event (fire-and-forget)."""
        ts = time.time()
        asyncio.create_task(
            self._emit_span("end", span_id, step, ts, ts_start=ts_start, error=error),
            name=f"span_end:{span_id}",
        )

    async def _emit_span(
        self,
        phase: str,
        span_id: str,
        step: str,
        ts: float,
        ts_start: float | None = None,
        error: bool = False,
    ) -> None:
        try:
            if not self._dragonfly or not self._dragonfly.connected:
                return
            fields: dict[str, str] = {
                "span_id": span_id,
                "operation": self._operation,
                "step": step,
                "session_id": self._session_id,
                "phase": phase,
                "ts": f"{ts:.6f}",
            }
            if phase == "end" and ts_start is not None:
                fields["ts_start"] = f"{ts_start:.6f}"
            if error:
                fields["error"] = "1"
            await self._dragonfly._client.xadd(
                _TIMING_STREAM, fields, maxlen=_STREAM_MAXLEN, approximate=True
            )
        except Exception as exc:
            logger.debug("SpanTracer emit failed: %s", exc)
