"""
Shared dependencies — backend initialization and FastAPI dependency injection.

All storage backends are initialized once at startup and accessed via app.state.
"""

import copy
import json
import logging

from fastapi import FastAPI, Request

from ...config import get_session_ttl
from ...storage import init_backends
from ...storage.short_term.dragonfly import DragonflyClient
from ...storage.short_term.memory import ShortTermMemory
from ...storage.long_term.episode_store import EpisodeStore
from ...storage.long_term.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


async def setup_backends(app: FastAPI) -> None:
    """Initialize all storage backends and attach to app.state."""
    from ...services.memory_service import MemoryService

    backends = await init_backends(session_ttl=get_session_ttl())

    app.state.dragonfly = backends["dragonfly"]
    app.state.short_term = backends["short_term"]
    app.state.episode_store = backends["episode_store"]
    app.state.knowledge_store = backends["knowledge_store"]
    app.state.artifact_store = backends["artifact_store"]
    app.state.ontology_store = backends["ontology_store"]
    app.state.causal_store = backends.get("causal_store")
    app.state.openai_client = backends["openai_client"]
    app.state.nats_client = backends.get("nats_client")
    app.state.service = MemoryService(
        episode_store=backends["episode_store"],
        knowledge_store=backends["knowledge_store"],
        artifact_store=backends["artifact_store"],
        ontology_store=backends.get("ontology_store"),
        causal_store=backends.get("causal_store"),
        dragonfly=backends["dragonfly"],
        short_term=backends["short_term"],
    )


async def teardown_backends(app: FastAPI) -> None:
    """Clean up storage backends."""
    if hasattr(app.state, "nats_client") and app.state.nats_client:
        await app.state.nats_client.close()
    if hasattr(app.state, "dragonfly"):
        await app.state.dragonfly.close()
    if hasattr(app.state, "openai_client"):
        await app.state.openai_client.close()
    logger.info("Storage backends shut down")


# --- Dependency helpers for routers ---


def get_dragonfly(request: Request) -> DragonflyClient:
    return request.app.state.dragonfly


def get_short_term(request: Request) -> ShortTermMemory:
    return request.app.state.short_term


def get_episode_store(request: Request) -> EpisodeStore:
    return request.app.state.episode_store


def get_ontology_store(request: Request) -> OntologyStore:
    return request.app.state.ontology_store


# --- Group-scoped store helpers (safe under concurrent requests) ---
#
# Every store has a mutable _group_id attribute used to scope Cypher queries.
# Directly mutating app.state.X._group_id is a race condition under concurrent
# requests: request A sets _group_id="a", awaits, request B sets _group_id="b",
# and when A resumes it queries under "b".
#
# copy.copy() creates a shallow copy: the graph connection, OpenAI client, and
# embedding model are shared references (correct — we never want multiple
# connections), while _group_id is a plain string attribute on the copy only.


def get_episode_store_for(request: Request, group_id: str) -> EpisodeStore:
    """Return a request-scoped EpisodeStore with group_id pre-set."""
    store = copy.copy(request.app.state.episode_store)
    store._group_id = group_id
    return store


def get_service(request: Request):
    """Return the shared MemoryService instance."""
    return request.app.state.service


# --- Shared utilities ---


def parse_json_labels(labels) -> list:
    """Parse a labels value that may be a JSON string or already a list."""
    if isinstance(labels, str):
        try:
            return json.loads(labels)
        except Exception:
            return []
    return labels if isinstance(labels, list) else []
