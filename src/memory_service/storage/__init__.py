"""
Storage layer — extracted from GeneralAgent framework.

Provides DragonflyDB (short-term) and FalkorDB (long-term) storage backends.
"""

import logging
from urllib.parse import urlparse

from .base_store import BaseStore, normalize_name
from .dragonfly import DragonflyClient, create_dragonfly_client
from .short_term import ShortTermMemory
from .episode_store import EpisodeStore, create_episode_store
from .knowledge_store import KnowledgeStore
from .artifact_store import ArtifactStore

# Backwards-compatible alias
normalize_label = normalize_name

logger = logging.getLogger(__name__)

__all__ = [
    "BaseStore",
    "normalize_name",
    "normalize_label",
    "DragonflyClient",
    "create_dragonfly_client",
    "ShortTermMemory",
    "EpisodeStore",
    "create_episode_store",
    "KnowledgeStore",
    "ArtifactStore",
    "init_backends",
]


async def init_backends(session_ttl: int = 3600) -> dict:
    """Create and connect all storage backends.

    Returns dict with keys: dragonfly, short_term, episode_store,
    knowledge_store, artifact_store, openai_client.
    """
    from openai import AsyncOpenAI
    from ..config import (
        get_dragonfly_url,
        get_falkordb_url,
        get_falkordb_graph_name,
        get_embedding_model,
        get_embedding_base_url,
        get_embedding_api_key,
    )

    # DragonflyDB
    dragonfly = DragonflyClient(redis_url=get_dragonfly_url(), session_ttl=session_ttl)
    if not await dragonfly.connect():
        raise RuntimeError(f"Cannot connect to DragonflyDB at {get_dragonfly_url()}")
    short_term = ShortTermMemory(dragonfly)

    # FalkorDB
    falkordb_url = get_falkordb_url()
    parsed = urlparse(falkordb_url)

    from falkordb.asyncio import FalkorDB

    db = FalkorDB(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6380,
        password=parsed.password,
    )
    graph = db.select_graph(get_falkordb_graph_name())

    # OpenAI embeddings client
    embedding_api_key = get_embedding_api_key()
    if not embedding_api_key:
        raise RuntimeError("Embedding API key not configured")

    openai_client = AsyncOpenAI(
        api_key=embedding_api_key,
        base_url=get_embedding_base_url(),
    )

    embedding_model = get_embedding_model()

    # Initialize stores
    episode_store = EpisodeStore(graph, openai_client, embedding_model)
    await episode_store.ensure_indexes()

    knowledge_store = KnowledgeStore(graph, openai_client, embedding_model)
    await knowledge_store.ensure_indexes()

    artifact_store = ArtifactStore(graph, openai_client, embedding_model)
    await artifact_store.ensure_indexes()

    # Optional NATS client
    from ..config import get_nats_enabled, get_nats_url

    nats_client = None
    if get_nats_enabled():
        from ..events.client import NatsClient
        from ..events.publisher import EpisodeEventPublisher

        nats_client = NatsClient(url=get_nats_url())
        await nats_client.connect()

        # Wire publisher so every episode store emits NATS events
        publisher = EpisodeEventPublisher(nats_client)
        episode_store.set_event_publisher(publisher)
        logger.info("NATS client initialized")

    logger.info("All storage backends initialized")

    return {
        "dragonfly": dragonfly,
        "short_term": short_term,
        "episode_store": episode_store,
        "knowledge_store": knowledge_store,
        "artifact_store": artifact_store,
        "openai_client": openai_client,
        "nats_client": nats_client,
    }
