"""
MCP (Model Context Protocol) server for Agent Memory Service.

Exposes memory operations as MCP tools.  Two modes:

  Integrated (default) — MCP SSE transport mounted on the existing FastAPI app
  at /mcp/sse.  No separate process; shares the same MemoryService instance.
  Claude Desktop / Claude Code SSE config:
      { "url": "http://localhost:9000/mcp/sse", "type": "sse" }

  Standalone stdio — separate process, useful for local Claude Desktop use.
  Claude Desktop stdio config:
      { "command": "memory-service-mcp" }
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP(
    "agent-memory-service",
    instructions=(
        "Agent memory service. Use memory_startup to begin a session and get "
        "background context, memory_observe to store/retrieve per-turn, and "
        "memory_search_knowledge for global semantic search across all sessions."
    ),
)

# ── Service wiring ────────────────────────────────────────────────────────────
#
# Integrated mode: FastAPI lifespan calls set_service(app.state.service) so
# MCP tools share the same MemoryService instance as REST and gRPC.
#
# Standalone stdio mode: _get_service() lazily initialises its own backends
# (same code path as main.py).

_svc = None
_init_lock: Optional[asyncio.Lock] = None


def set_service(svc) -> None:
    """Inject a pre-created MemoryService (called from FastAPI lifespan)."""
    global _svc
    _svc = svc


async def _get_service():
    """Return the MemoryService, lazily initialising backends if needed."""
    global _svc, _init_lock
    if _svc is not None:
        return _svc

    # Fallback: standalone stdio mode — spin up our own backends.
    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        if _svc is not None:
            return _svc

        from ...storage import init_backends
        from ...services.memory_service import MemoryService
        from ...config import get_session_ttl

        logger.info("MCP: initialising Agent Memory Service backends…")
        backends = await init_backends(session_ttl=get_session_ttl())
        _svc = MemoryService(
            episode_store=backends["episode_store"],
            knowledge_store=backends["knowledge_store"],
            artifact_store=backends["artifact_store"],
            ontology_store=backends.get("ontology_store"),
            dragonfly=backends["dragonfly"],
            short_term=backends["short_term"],
        )
        logger.info("MCP: MemoryService ready")
        return _svc


# ── Input models (FastMCP infers JSON schema from Pydantic) ──────────────────


class KnowledgeEntryInput(BaseModel):
    content: str = Field(..., description="The knowledge content to store")
    knowledge_type: str = Field(
        "fact",
        description="Type of knowledge: fact, pattern, insight, preference, procedure",
    )
    labels: List[str] = Field(
        default_factory=list, description="Semantic labels / tags"
    )
    confidence: float = Field(
        0.8, ge=0.0, le=1.0, description="Confidence score (0–1)"
    )
    event_date: Optional[str] = Field(
        None, description="Optional ISO 8601 date the event occurred (YYYY-MM-DD)"
    )


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
async def memory_startup(
    task: str,
    session_id: Optional[str] = None,
    parent_session_id: Optional[str] = None,
    workflow_id: str = "default",
) -> str:
    """
    Initialise a session and retrieve background context.

    Call this at the start of every new task/conversation.  Returns a
    `session_id` (auto-generated UUID if you don't supply one) plus a
    synthesised `background_narrative` with relevant memories from prior
    sessions.  Pass the returned `session_id` to all subsequent
    `memory_observe` calls.

    For hierarchical tasks supply `parent_session_id` to inherit the
    parent session's memories automatically.
    """
    svc = await _get_service()
    result = await svc.startup_pipeline(
        group_id=session_id or None,
        workflow_id=workflow_id,
        task=task,
        parent_session_id=parent_session_id or None,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def memory_observe(
    session_id: str,
    content: str,
    read_only: bool = False,
    parent_session_id: Optional[str] = None,
    top_k: int = 10,
) -> str:
    """
    Store a memory and/or retrieve relevant context for a session.

    Write path (default, `read_only=False`): stores `content` as an episode
    and returns relevant memories from the session (+ ancestor sessions).

    Read-only path (`read_only=True`): only retrieves relevant memories
    without writing — useful for mid-turn lookups.

    Returns a JSON object with:
      - `context_entries`: list of relevant memory snippets
      - `session_id`: echoed back
      - `background_narrative`: synthesised summary (write path only)
    """
    svc = await _get_service()
    result = await svc.observe(
        session_id=session_id,
        content=content,
        read_only=read_only,
        parent_session_id=parent_session_id or None,
        top_k=top_k,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def memory_search_knowledge(
    query: str,
    session_id: Optional[str] = None,
    top_k: int = 10,
    min_score: float = 0.50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Semantic search over the knowledge base.

    Omit `session_id` to search globally across **all** sessions.
    Supply `session_id` to scope results to that session only.

    Optionally filter by `start_date` / `end_date` (ISO 8601, YYYY-MM-DD)
    to retrieve time-bounded facts.

    Returns a JSON array of knowledge records ordered by relevance score.
    """
    svc = await _get_service()
    results = await svc.search_knowledge(
        group_id=session_id or None,
        query=query,
        top_k=top_k,
        min_score=min_score,
        start_date=start_date or None,
        end_date=end_date or None,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def memory_search_episodes(
    session_id: str,
    query: str,
    top_k: int = 10,
    min_score: float = 0.40,
) -> str:
    """
    Semantic search over raw episode history for a session.

    Episodes are individual observation turns — the raw conversational
    record.  Use `memory_search_knowledge` for distilled facts; use this
    tool to recall specific conversation moments.

    Returns a JSON array of episode records ordered by relevance score.
    """
    svc = await _get_service()
    results = await svc.search_episodes(
        group_id=session_id,
        query=query,
        top_k=top_k,
        min_score=min_score,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def memory_store_knowledge(
    session_id: str,
    entries: List[KnowledgeEntryInput],
    source_mission: str,
) -> str:
    """
    Directly store structured knowledge entries for a session.

    Prefer `memory_observe` for automatic extraction from raw text.
    Use this tool when you already have structured facts to persist
    (e.g. after reasoning, tool outputs, or explicit user statements).

    Returns the list of UUIDs assigned to the stored knowledge nodes.
    """
    svc = await _get_service()
    uuids = await svc.store_knowledge(
        group_id=session_id,
        entries=[e.model_dump() for e in entries],
        source_mission=source_mission,
        mission_status="success",
    )
    return json.dumps({"uuids": uuids}, indent=2)


@mcp.tool()
async def memory_run_curation(
    session_id: str,
    mission_summary: str = "",
    mission_status: str = "success",
) -> str:
    """
    Trigger LLM-powered memory curation for a session.

    Curation: reflects on recent episodes → extracts knowledge nodes →
    extracts artifact nodes → compresses raw events.  This runs the full
    pipeline and returns a summary of what was produced.

    Call at the end of a task or when you want to consolidate memories.
    `mission_summary` — brief description of what was accomplished.
    `mission_status`  — "success" or "partial" or "failed".
    """
    svc = await _get_service()
    mission_data: Dict[str, Any] = {}
    if mission_summary:
        mission_data["task"] = mission_summary
        mission_data["status"] = mission_status
    result = await svc.run_curation(
        group_id=session_id,
        workflow_id="default",
        mission_data=mission_data,
    )
    return json.dumps(result, indent=2, default=str)


# ── Entrypoints ───────────────────────────────────────────────────────────────


def cli():
    """CLI entrypoint — runs the MCP server over stdio."""
    logging.basicConfig(
        level=logging.WARNING,  # keep stdio clean; MCP client sees only JSON
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    cli()
