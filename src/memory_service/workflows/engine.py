"""Workflow engine — executes a Workflow DAG via NATS pipeline queues."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from .base import Stage, Workflow

logger = logging.getLogger(__name__)


def _sanitize_group_id(group_id: str) -> str:
    """Replace dots/spaces with hyphens for NATS subject safety."""
    return group_id.replace(".", "-").replace(" ", "-")


def _json_safe(d: dict) -> dict:
    """Return a copy with only JSON-serializable top-level values."""
    out = {}
    for k, v in d.items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError, OverflowError):
            pass
    return out


class WorkflowEngine:
    """Executes a :class:`Workflow` DAG.

    * **sync stages** are called directly — the caller blocks until the
      handler returns.
    * **async stages** are published to NATS JetStream (fire-and-forget)
      or dispatched as background tasks if NATS is unavailable.
    """

    def __init__(self, nats_client=None) -> None:
        self._nats = nats_client

    async def execute(
        self,
        workflow: Workflow,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Walk *workflow* in topological order and run each stage.

        Returns a dict mapping sync stage names to their results.
        """
        results: Dict[str, Any] = {}

        for stage in workflow.topological_order():
            # Merge base context with results from completed stages
            payload: Dict[str, Any] = {
                **context,
                **{f"{k}_result": v for k, v in results.items()},
            }

            if stage.sync:
                try:
                    result = await asyncio.wait_for(
                        stage.handler(payload),
                        timeout=stage.timeout,
                    )
                    results[stage.name] = result
                except asyncio.TimeoutError:
                    logger.error(
                        "WorkflowEngine: sync stage '%s' timed out (%.0fs)",
                        stage.name,
                        stage.timeout,
                    )
                except Exception as e:
                    logger.error(
                        "WorkflowEngine: sync stage '%s' failed: %s",
                        stage.name,
                        e,
                    )
            else:
                await self._queue_async(stage, payload)

        return results

    async def _queue_async(self, stage: Stage, payload: Dict[str, Any]) -> None:
        """Publish to JetStream or dispatch as background task."""
        if self._nats:
            safe = _json_safe(payload)
            gid = _sanitize_group_id(payload.get("group_id", "default"))
            subject = f"memory.pipeline.{stage.name}.{gid}"
            try:
                await self._nats.jetstream.publish(
                    subject,
                    json.dumps(safe).encode(),
                )
                logger.info("WorkflowEngine: queued async stage '%s'", stage.name)
            except Exception as e:
                logger.error(
                    "WorkflowEngine: failed to queue async stage '%s': %s",
                    stage.name,
                    e,
                )
        else:
            asyncio.create_task(self._run_async_safe(stage, payload))

    @staticmethod
    async def _run_async_safe(stage: Stage, payload: Dict[str, Any]) -> None:
        try:
            await stage.handler(payload)
        except Exception as e:
            logger.error(
                "WorkflowEngine: async stage '%s' failed: %s",
                stage.name,
                e,
                exc_info=True,
            )
