"""Curation worker — event-driven episode consolidation.

Subscribes to memory.episode.stored.* events, accumulates per group_id,
and triggers curation when a group accumulates enough pending raw episodes.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional

import nats.js.api

from ..messaging.schemas import EpisodeStoredEvent

logger = logging.getLogger(__name__)


class GroupAccumulator:
    """Tracks pending episode counts per group with timeout-based flush."""

    def __init__(self, min_episodes: int = 3, max_wait_seconds: float = 30.0):
        self._min_episodes = min_episodes
        self._max_wait = max_wait_seconds
        self._groups: Dict[str, List[dict]] = defaultdict(list)
        self._first_seen: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def add(self, event: dict) -> Optional[str]:
        """Add an episode event. Returns group_id if threshold reached."""
        try:
            parsed = EpisodeStoredEvent.model_validate(event)
        except Exception as exc:
            logger.warning("Dropping malformed episode event: %s — %s", event, exc)
            return None

        group_id = parsed.group_id
        episode_type = parsed.episode_type
        status = parsed.consolidation_status

        # Only accumulate pending raw episodes
        if episode_type != "raw" or status != "pending":
            return None

        async with self._lock:
            self._groups[group_id].append(parsed.model_dump())
            if group_id not in self._first_seen:
                self._first_seen[group_id] = time.time()

            if len(self._groups[group_id]) >= self._min_episodes:
                return group_id
            return None

    async def pop_group(self, group_id: str) -> List[dict]:
        """Pop accumulated events for a group."""
        async with self._lock:
            events = self._groups.pop(group_id, [])
            self._first_seen.pop(group_id, None)
            return events

    async def get_timed_out_groups(self) -> List[str]:
        """Return group_ids that have been waiting longer than max_wait."""
        now = time.time()
        async with self._lock:
            return [
                gid
                for gid, first in self._first_seen.items()
                if (now - first) > self._max_wait and len(self._groups[gid]) > 0
            ]


class CurationWorker:
    """Event-driven curation worker.

    Subscribes to memory.episode.stored.* via JetStream pull consumer.
    Accumulates episodes per group_id. When a group has >= min_episodes
    pending, triggers curation immediately.

    Also runs a periodic check for timed-out groups (groups with some
    but not enough episodes that have been waiting too long).
    """

    def __init__(
        self,
        nats_client,
        handler,
        episode_store,
        publisher,
        min_episodes: int = 3,
        max_wait_seconds: float = 30.0,
        max_concurrent: int = 2,
        ontology_store=None,
        dragonfly=None,
    ):
        self._nats = nats_client
        self._handler = handler
        self._episode_store = episode_store
        self._publisher = publisher
        self._ontology_store = ontology_store
        self._dragonfly = dragonfly
        self._accumulator = GroupAccumulator(min_episodes, max_wait_seconds)
        self._max_wait = max_wait_seconds
        self._running = False
        self._sub = None
        self._curation_semaphore = asyncio.Semaphore(max_concurrent)

    async def run(self) -> None:
        """Main loop — subscribe and process episode events."""
        self._running = True
        js = self._nats.jetstream

        self._sub = await js.pull_subscribe(
            "memory.episode.stored.*",
            durable="curation-worker",
            config=nats.js.api.ConsumerConfig(
                ack_wait=300,
                max_deliver=3,
                max_ack_pending=20,
            ),
        )

        logger.info("CurationWorker started (pull subscriber)")

        try:
            await asyncio.gather(
                self._process_messages(),
                self._check_timeouts(),
            )
        except asyncio.CancelledError:
            self._running = False
            logger.info("CurationWorker stopped")

    async def _process_messages(self) -> None:
        """Fetch and process messages from JetStream."""
        while self._running:
            try:
                msgs = await self._sub.fetch(batch=10, timeout=5)
                for msg in msgs:
                    try:
                        event = json.loads(msg.data.decode())
                        group_id = await self._accumulator.add(event)
                        await msg.ack()

                        if group_id:
                            asyncio.create_task(self._trigger_curation(group_id, "threshold"))
                    except Exception as e:
                        logger.error(f"Failed to process message: {e}")
                        try:
                            await msg.nak()
                        except Exception:
                            pass
            except nats.errors.TimeoutError:
                pass
            except Exception as e:
                if self._running:
                    logger.error(f"Message fetch error: {e}")
                    await asyncio.sleep(1)

    async def _check_timeouts(self) -> None:
        """Periodically check for groups that have waited too long."""
        while self._running:
            await asyncio.sleep(self._max_wait / 2)
            try:
                timed_out = await self._accumulator.get_timed_out_groups()
                for group_id in timed_out:
                    asyncio.create_task(self._trigger_curation(group_id, "timeout"))
            except Exception as e:
                logger.error(f"Timeout check error: {e}")

    async def _trigger_curation(self, group_id: str, reason: str) -> None:
        """Run curation for a group, guarded by semaphore."""
        events = await self._accumulator.pop_group(group_id)
        if not events:
            return

        async with self._curation_semaphore:
            start_time = time.time()
            logger.info(
                f"Curation triggered for '{group_id}': {len(events)} episodes, reason={reason}"
            )
            try:
                source_uuids = [e["episode_uuid"] for e in events]

                # Fetch content + knowledge_extracted flag from FalkorDB
                result = await self._episode_store._graph.query(
                    """MATCH (e:Episode)
                    WHERE e.uuid IN $uuids AND e.episode_type = 'raw'
                    RETURN e.uuid AS uuid, e.content AS content,
                           coalesce(e.knowledge_extracted, false) AS knowledge_extracted
                    ORDER BY e.created_at ASC""",
                    params={"uuids": source_uuids},
                )
                episode_contents = {row[0]: row[1] for row in result.result_set if row[0]}
                all_knowledge_extracted = all(row[2] for row in result.result_set if row[0])
                combined = "\n---\n".join(episode_contents.get(uuid, "") for uuid in source_uuids)

                # Pull tool events from DragonflyDB to enrich knowledge extraction
                tool_context = ""
                if self._dragonfly:
                    try:
                        raw_events = await self._dragonfly.get_events_for_group(
                            group_id=group_id,
                            count=100,
                            event_types=["tool_call", "tool_result", "observation", "tool_use"],
                        )
                        if raw_events:
                            raw_events.sort(key=lambda e: e.get("timestamp", 0))
                            lines = []
                            for e in raw_events:
                                etype = e.get("type", "event")
                                data = e.get("data", {})
                                if etype == "tool_call":
                                    tool = data.get("tool", data.get("tool_name", "unknown"))
                                    inp = str(data.get("input", data.get("args", "")))[:300]
                                    lines.append(f"[tool_call] {tool}: {inp}")
                                elif etype == "tool_result":
                                    tool = data.get("tool", data.get("tool_name", "unknown"))
                                    out = str(data.get("output", data.get("result", "")))[:500]
                                    ok = "ok" if data.get("success", True) else "FAILED"
                                    lines.append(f"[tool_result:{ok}] {tool}: {out}")
                                else:
                                    content = str(data.get("content", str(data)))[:300]
                                    lines.append(f"[{etype}] {content}")
                            tool_context = "\n".join(lines)
                    except Exception as exc:
                        logger.warning("Could not fetch tool events for '%s': %s", group_id, exc)

                mission_data = {
                    "task": f"Extract knowledge from conversation episodes in group '{group_id}'",
                    "status": "completed",
                    "run_id": f"nats_{group_id}_{int(time.time())}",
                    "output": combined,
                    "context": tool_context,
                    "data_source_type": "conversation",
                    "iterations": 1,
                    "state": {
                        "state_description": combined[:2000],
                        "outputs": [{"iteration": 1, "output": combined[:4000]}],
                    },
                }

                if all_knowledge_extracted:
                    logger.info(
                        f"Skipping knowledge extraction for '{group_id}': "
                        f"all {len(source_uuids)} episodes already extracted"
                    )
                    curation_result = {
                        "knowledge_count": 0,
                        "artifact_count": 0,
                        "reflection_uuid": "",
                    }
                else:
                    curation_result = await self._handler.run_curation(
                        {
                            "scope": {"group_id": group_id, "workflow_id": "nats_curation"},
                            "mission_data_json": mission_data,
                            "source_episode_uuids": source_uuids,
                        }
                    )

                # Step 8: Ontology update (entity extraction + summary refresh + RELATES edges)
                if self._ontology_store is not None:
                    try:
                        from ..intelligence.graph.ontology_pipeline import update_group_ontology

                        episodes_with_uuid = [
                            {"uuid": uuid, "content": episode_contents.get(uuid, "")}
                            for uuid in source_uuids
                        ]
                        await update_group_ontology(
                            ontology_store=self._ontology_store,
                            group_id=group_id,
                            episodes=episodes_with_uuid,
                            combined_text=combined,
                        )
                    except Exception as e:
                        logger.error(
                            "Ontology update failed for '%s': %s", group_id, e, exc_info=True
                        )

                # Mark episodes consolidated
                consolidated = await self._episode_store.mark_episodes_consolidated(source_uuids)

                # Compress
                compressed_uuid = ""
                if len(source_uuids) >= 2:
                    compressed_uuid = await self._episode_store.compress_raw_episodes(
                        group_id=group_id,
                        source_uuids=source_uuids,
                        summary_content=combined[:3000],
                    )

                duration_ms = (time.time() - start_time) * 1000

                # Record curation latency (fire-and-forget, runs in parallel)
                if self._dragonfly:
                    asyncio.create_task(
                        self._dragonfly.record_latency("BG:curation/trigger", duration_ms)
                    )

                await self._publisher.curation_completed(
                    group_id=group_id,
                    result={
                        "episodes_consolidated": consolidated,
                        "knowledge_count": curation_result.get("knowledge_count", 0),
                        "artifact_count": curation_result.get("artifact_count", 0),
                        "compressed_uuid": compressed_uuid,
                        "reflection_uuid": curation_result.get("reflection_uuid", ""),
                    },
                    duration_ms=duration_ms,
                )

                logger.info(
                    f"Curation completed for '{group_id}': "
                    f"consolidated={consolidated}, "
                    f"knowledge={curation_result.get('knowledge_count', 0)}, "
                    f"duration={duration_ms:.0f}ms"
                )

            except Exception as e:
                logger.error(f"Curation failed for '{group_id}': {e}", exc_info=True)
