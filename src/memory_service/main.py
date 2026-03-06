"""
Agent Memory Service — main entrypoint.

Starts both gRPC and REST servers concurrently.
"""

import asyncio
import logging
import signal
import sys
from urllib.parse import urlparse

import uvicorn
from openai import AsyncOpenAI

from .config import (
    get_dragonfly_url,
    get_falkordb_url,
    get_falkordb_graph_name,
    get_embedding_model,
    get_embedding_base_url,
    get_embedding_api_key,
    get_grpc_port,
    get_rest_host,
    get_rest_port,
    get_background_enabled,
    get_background_interval,
    get_background_batch_size,
    get_background_min_episodes,
)
from .storage.dragonfly import DragonflyClient
from .storage.short_term import ShortTermMemory
from .storage.episode_store import EpisodeStore
from .storage.knowledge_store import KnowledgeStore
from .storage.artifact_store import ArtifactStore
from .grpc.service_handler import MemoryServiceHandler
from .grpc.server import create_grpc_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def init_backends():
    """Initialize all storage backends."""

    # DragonflyDB
    dragonfly = DragonflyClient(redis_url=get_dragonfly_url())
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

    logger.info("All storage backends initialized")

    return {
        "dragonfly": dragonfly,
        "short_term": short_term,
        "episode_store": episode_store,
        "knowledge_store": knowledge_store,
        "artifact_store": artifact_store,
        "openai_client": openai_client,
    }


async def run_grpc_server(handler: MemoryServiceHandler, port: int):
    """Start and run the gRPC server."""
    server = await create_grpc_server(handler, port=port)
    await server.start()
    logger.info(f"gRPC server started on port {port}")

    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("gRPC server stopped")


async def run_rest_server(host: str, port: int):
    """Start and run the REST server."""
    from .rest.app import create_app

    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Main entrypoint — starts gRPC + REST servers."""
    logger.info("Agent Memory Service starting...")

    backends = await init_backends()

    handler = MemoryServiceHandler(
        dragonfly=backends["dragonfly"],
        short_term=backends["short_term"],
        episode_store=backends["episode_store"],
        knowledge_store=backends["knowledge_store"],
        artifact_store=backends["artifact_store"],
    )

    grpc_port = get_grpc_port()
    rest_host = get_rest_host()
    rest_port = get_rest_port()

    # Build task list: gRPC + REST + optional REM worker
    tasks = [
        run_grpc_server(handler, grpc_port),
        run_rest_server(rest_host, rest_port),
    ]

    if get_background_enabled():
        from .background.rem_worker import REMWorker

        rem_worker = REMWorker(
            handler=handler,
            episode_store=backends["episode_store"],
            interval_seconds=get_background_interval(),
            batch_size=get_background_batch_size(),
            min_episodes=get_background_min_episodes(),
        )
        tasks.append(rem_worker.run())
        logger.info("REM background worker enabled")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await backends["dragonfly"].close()
        await backends["openai_client"].close()
        logger.info("Agent Memory Service stopped")


def cli():
    """CLI entrypoint."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
