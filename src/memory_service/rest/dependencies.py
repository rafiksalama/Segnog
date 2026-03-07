"""
Shared dependencies — backend initialization and FastAPI dependency injection.

All storage backends are initialized once at startup and accessed via app.state.
"""

import logging

from fastapi import FastAPI, Request

from ..config import get_session_ttl
from ..storage import init_backends
from ..storage.dragonfly import DragonflyClient
from ..storage.short_term import ShortTermMemory
from ..storage.episode_store import EpisodeStore
from ..storage.knowledge_store import KnowledgeStore
from ..storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


async def setup_backends(app: FastAPI) -> None:
    """Initialize all storage backends and attach to app.state."""
    backends = await init_backends(session_ttl=get_session_ttl())

    app.state.dragonfly = backends["dragonfly"]
    app.state.short_term = backends["short_term"]
    app.state.episode_store = backends["episode_store"]
    app.state.knowledge_store = backends["knowledge_store"]
    app.state.artifact_store = backends["artifact_store"]
    app.state.openai_client = backends["openai_client"]


async def teardown_backends(app: FastAPI) -> None:
    """Clean up storage backends."""
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


def get_knowledge_store(request: Request) -> KnowledgeStore:
    return request.app.state.knowledge_store


def get_artifact_store(request: Request) -> ArtifactStore:
    return request.app.state.artifact_store
