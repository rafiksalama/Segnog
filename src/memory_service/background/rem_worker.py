"""
REM Sleep Worker — periodic background consolidation.

Scans for groups with pending raw episodes, scores them by priority
(episode count + age), and runs the curation pipeline with:
- Source traceability (reflection links back to raw episodes)
- Episode lifecycle (raw episodes marked as consolidated)
- Temporal compression (raw episodes merged into compressed summaries)
"""

import asyncio
import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class REMWorker:
    """Background worker that periodically consolidates raw episodes."""

    def __init__(
        self,
        handler,
        episode_store,
        interval_seconds: int = 60,
        batch_size: int = 5,
        min_episodes: int = 3,
    ):
        self._handler = handler
        self._episode_store = episode_store
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._min_episodes = min_episodes
        self._running = False

    async def run(self) -> None:
        """Main loop — runs until cancelled."""
        self._running = True
        logger.info(
            f"REM worker started (interval={self._interval}s, "
            f"batch={self._batch_size}, min_episodes={self._min_episodes})"
        )

        try:
            while self._running:
                try:
                    await self._run_cycle()
                except Exception as e:
                    logger.error(f"REM cycle error: {e}", exc_info=True)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            self._running = False
            logger.info("REM worker stopped")

    async def _run_cycle(self) -> None:
        """Find pending groups by priority and consolidate each."""
        groups = await self._find_pending_groups()
        if not groups:
            return

        logger.info(f"REM cycle: {len(groups)} group(s) to consolidate")
        for group_info in groups:
            gid = group_info["group_id"]
            try:
                result = await self._consolidate_group(group_info)
                logger.info(
                    f"REM consolidated '{gid}': "
                    f"{result.get('episodes_consolidated', 0)} episodes, "
                    f"compressed={result.get('compressed_uuid', '')[:8] or 'none'}"
                )
            except Exception as e:
                logger.error(f"REM failed for '{gid}': {e}", exc_info=True)
            await asyncio.sleep(0.1)

    async def _find_pending_groups(self) -> List[Dict[str, Any]]:
        """
        Discover groups with pending raw episodes, scored by priority.

        Priority = raw_count * 0.5 + age_hours * 0.5
        Groups with more unprocessed episodes and older pending episodes
        are processed first.
        """
        now = time.time()
        cypher = """
            MATCH (e:Episode)
            WHERE e.consolidation_status = 'pending'
              AND e.episode_type = 'raw'
            WITH e.group_id AS gid, count(e) AS raw_count, min(e.created_at) AS oldest_ts
            WHERE raw_count >= $min_episodes
            RETURN gid, raw_count, oldest_ts
            ORDER BY raw_count DESC
            LIMIT $limit
        """
        try:
            result = await self._episode_store._graph.query(
                cypher,
                params={
                    "min_episodes": self._min_episodes,
                    "limit": self._batch_size * 3,
                },
            )
        except Exception as e:
            logger.debug(f"REM group discovery failed: {e}")
            return []

        groups = []
        for row in result.result_set:
            gid, raw_count, oldest_ts = row[0], row[1], row[2]
            if not gid:
                continue
            age_hours = (now - (oldest_ts or now)) / 3600
            score = (raw_count * 0.5) + (age_hours * 0.5)
            groups.append({
                "group_id": gid,
                "raw_count": raw_count,
                "score": score,
            })

        groups.sort(key=lambda x: x["score"], reverse=True)
        return groups[:self._batch_size]

    async def _consolidate_group(self, group_info: dict) -> dict:
        """
        Full consolidation for a group:
        1. Fetch pending raw episodes (with UUIDs)
        2. Run curation pipeline with source traceability
        3. Mark episodes as consolidated (durable lifecycle)
        4. Temporal compression into summary episode
        """
        group_id = group_info["group_id"]

        # Fetch pending raw episodes, oldest first
        cypher = """
            MATCH (e:Episode)
            WHERE e.group_id = $group_id
              AND e.episode_type = 'raw'
              AND e.consolidation_status = 'pending'
            RETURN e.uuid AS uuid, e.content AS content, e.created_at AS created_at
            ORDER BY e.created_at ASC
            LIMIT 20
        """
        result = await self._episode_store._graph.query(
            cypher, params={"group_id": group_id}
        )
        episodes = [
            {"uuid": row[0], "content": row[1], "created_at": row[2]}
            for row in result.result_set
            if row[0]
        ]

        if not episodes:
            return {"skipped": True, "reason": "no pending episodes"}

        source_uuids = [ep["uuid"] for ep in episodes]
        combined_content = "\n---\n".join(ep["content"] for ep in episodes[:10])

        # Build mission_data for curation
        mission_data = {
            "task": f"Background consolidation for group '{group_id}'",
            "status": "completed",
            "run_id": f"rem_{group_id}_{int(time.time())}",
            "state": {"state_description": combined_content[:2000]},
        }

        # Run curation with source traceability
        curation_result = await self._handler.run_curation({
            "scope": {"group_id": group_id, "workflow_id": "rem_worker"},
            "mission_data_json": mission_data,
            "source_episode_uuids": source_uuids,
        })

        # Mark source episodes as consolidated (durable state)
        consolidated_count = await self._episode_store.mark_episodes_consolidated(
            source_uuids
        )

        # Temporal compression: merge into one compressed summary
        compressed_uuid = ""
        if len(episodes) >= 2:
            compressed_uuid = await self._episode_store.compress_raw_episodes(
                group_id=group_id,
                source_uuids=source_uuids,
                summary_content=combined_content[:3000],
            )

        return {
            "group_id": group_id,
            "episodes_found": len(episodes),
            "episodes_consolidated": consolidated_count,
            "compressed_uuid": compressed_uuid,
            "curation": curation_result,
        }
