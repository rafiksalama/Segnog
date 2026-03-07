"""
Agent Memory Service — main entrypoint.

Starts both gRPC and REST servers concurrently.
"""

import asyncio
import logging

import uvicorn

from .config import (
    get_grpc_port,
    get_rest_host,
    get_rest_port,
    get_session_ttl,
    get_background_enabled,
    get_background_interval,
    get_background_batch_size,
    get_background_min_episodes,
)
from .storage import init_backends
from .grpc.service_handler import MemoryServiceHandler
from .grpc.server import create_grpc_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


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

    backends = await init_backends(session_ttl=get_session_ttl())

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
