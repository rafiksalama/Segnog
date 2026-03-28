"""
Event Compression — Summarize old events into a compressed episode.

Raw events in DragonflyDB expire naturally via TTL. This module
summarizes them into a single compressed episode in FalkorDB before
they expire, preserving the information in a denser form.
"""

import json
import logging
from typing import Optional

from ..llm.client import llm_call
from ...config import get_flash_model

logger = logging.getLogger(__name__)


async def compress_events(
    short_term_memory,
    episode_store,
    run_id: str,
    state_description: str = "",
    model: Optional[str] = None,
) -> dict:
    """
    Compress old raw events into a summary episode.

    Args:
        short_term_memory: ShortTermMemory instance for reading events.
        episode_store: EpisodeStore instance for storing compressed episode.
        run_id: Workflow run ID whose events to compress.
        state_description: Agent's final state narrative.
        model: Model to use (defaults to flash model).

    Returns:
        Dict with "compressed" (bool) and "episode_uuid" (str).
    """
    model = model or get_flash_model()

    if short_term_memory is None or episode_store is None:
        logger.warning("Memory or episode store not available for compression")
        return {"compressed": False, "episode_uuid": ""}

    try:
        events = await short_term_memory.get("recent_events:50")
        if not events or len(events) < 10:
            logger.debug("Not enough events to compress")
            return {"compressed": False, "episode_uuid": ""}

        event_lines = []
        for e in events:
            etype = e.get("type", "unknown")
            content = e.get("content", "")
            if isinstance(content, dict):
                content = json.dumps(content)[:200]
            else:
                content = str(content)[:200]
            event_lines.append(f"[{etype}] {content}")

        events_text = "\n".join(event_lines[:30])

        context_hint = f"\nAgent's final state: {state_description}\n" if state_description else ""
        summary = await llm_call(
            f"Summarize these agent execution events into a concise paragraph:{context_hint}\n\n{events_text}\n\nSummary:",
            model=model,
            temperature=0.2,
            max_tokens=196000,
        )

        episode_uuid = await episode_store.store_episode(
            content=summary.strip(),
            metadata={"run_id": run_id, "source": "compression", "event_count": len(events)},
            episode_type="compressed",
        )

        logger.info(f"Compressed {len(events)} events into episode for run {run_id[:8]}")
        return {"compressed": True, "episode_uuid": episode_uuid}

    except Exception as e:
        logger.error(f"Event compression failed: {e}")
        return {"compressed": False, "episode_uuid": ""}
