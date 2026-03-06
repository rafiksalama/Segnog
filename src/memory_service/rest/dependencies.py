"""
Shared dependencies — backend initialization and FastAPI dependency injection.

All storage backends are initialized once at startup and accessed via app.state.
"""

import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from openai import AsyncOpenAI

from ..config import (
    get_dragonfly_url,
    get_falkordb_url,
    get_falkordb_graph_name,
    get_embedding_model,
    get_embedding_base_url,
    get_embedding_api_key,
)
from ..storage.dragonfly import DragonflyClient
from ..storage.short_term import ShortTermMemory
from ..storage.episode_store import EpisodeStore
from ..storage.knowledge_store import KnowledgeStore
from ..storage.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


async def setup_backends(app: FastAPI) -> None:
    """Initialize all storage backends and attach to app.state."""

    # DragonflyDB
    dragonfly = DragonflyClient(redis_url=get_dragonfly_url())
    if not await dragonfly.connect():
        raise RuntimeError(f"Cannot connect to DragonflyDB at {get_dragonfly_url()}")
    app.state.dragonfly = dragonfly
    app.state.short_term = ShortTermMemory(dragonfly)

    # FalkorDB + OpenAI embeddings
    falkordb_url = get_falkordb_url()
    parsed = urlparse(falkordb_url)

    from falkordb.asyncio import FalkorDB

    db = FalkorDB(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6380,
        password=parsed.password,
    )
    graph = db.select_graph(get_falkordb_graph_name())
    app.state.falkordb_graph = graph

    embedding_api_key = get_embedding_api_key()
    if not embedding_api_key:
        raise RuntimeError("Embedding API key not configured")

    openai_client = AsyncOpenAI(
        api_key=embedding_api_key,
        base_url=get_embedding_base_url(),
    )
    app.state.openai_client = openai_client

    embedding_model = get_embedding_model()

    episode_store = EpisodeStore(graph, openai_client, embedding_model)
    await episode_store.ensure_indexes()
    app.state.episode_store = episode_store

    knowledge_store = KnowledgeStore(graph, openai_client, embedding_model)
    await knowledge_store.ensure_indexes()
    app.state.knowledge_store = knowledge_store

    artifact_store = ArtifactStore(graph, openai_client, embedding_model)
    await artifact_store.ensure_indexes()
    app.state.artifact_store = artifact_store

    logger.info("All storage backends initialized")


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
