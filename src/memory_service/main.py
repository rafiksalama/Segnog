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
    get_nats_enabled,
    get_nats_url,
    get_nats_curation_min_episodes,
    get_nats_curation_max_wait,
    get_nats_curation_max_concurrent,
)
from .storage import init_backends
from .services.memory_service import MemoryService
from .transport.grpc.service_handler import MemoryServiceHandler
from .transport.grpc.server import create_grpc_server

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
    from .transport.rest.app import create_app

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

    if backends.get("ontology_store") is None:
        logger.warning(
            "OntologyStore not available — ontology features (entity extraction, "
            "node search, relationship inference) will be disabled. "
            "Check FalkorDB connectivity and schema_org data path."
        )

    # NATS bootstrap (messaging concerns live here, not in storage/)
    nats_client = None
    if get_nats_enabled():
        from .messaging.client import NatsClient
        from .messaging.publisher import EpisodeEventPublisher

        nats_client = NatsClient(url=get_nats_url())
        await nats_client.connect()

        publisher = EpisodeEventPublisher(nats_client)
        backends["episode_store"].set_event_publisher(publisher)
        logger.info("NATS client initialized")

    svc = MemoryService(
        episode_store=backends["episode_store"],
        knowledge_store=backends["knowledge_store"],
        artifact_store=backends["artifact_store"],
        ontology_store=backends.get("ontology_store"),
        dragonfly=backends["dragonfly"],
        short_term=backends["short_term"],
    )
    handler = MemoryServiceHandler(service=svc)

    grpc_port = get_grpc_port()
    rest_host = get_rest_host()
    rest_port = get_rest_port()

    # Build task list: gRPC + REST + background workers
    tasks = [
        run_grpc_server(handler, grpc_port),
        run_rest_server(rest_host, rest_port),
    ]

    if nats_client:
        # NATS event-driven curation replaces polling-based REM worker
        from .messaging.publisher import EpisodeEventPublisher
        from .workers.curation_worker import CurationWorker
        from .workers.rem_sweep_worker import REMSweepPublisher, REMSweepWorker

        publisher = backends["episode_store"]._event_publisher or EpisodeEventPublisher(nats_client)

        curation_worker = CurationWorker(
            nats_client=nats_client,
            handler=handler,
            episode_store=backends["episode_store"],
            publisher=publisher,
            min_episodes=get_nats_curation_min_episodes(),
            max_wait_seconds=get_nats_curation_max_wait(),
            max_concurrent=get_nats_curation_max_concurrent(),
            ontology_store=backends.get("ontology_store"),
            dragonfly=backends["dragonfly"],
        )
        tasks.append(curation_worker.run())

        sweep_publisher = REMSweepPublisher(
            nats_client=nats_client,
            interval_seconds=get_background_interval(),
        )
        sweep_worker = REMSweepWorker(
            nats_client=nats_client,
            handler=handler,
            episode_store=backends["episode_store"],
            batch_size=get_background_batch_size(),
            min_episodes=1,
            ontology_store=backends.get("ontology_store"),
            dragonfly=backends["dragonfly"],
        )
        tasks.append(sweep_publisher.run())
        tasks.append(sweep_worker.run())
        logger.info("NATS event workers enabled (curation + sweep)")

    elif get_background_enabled():
        # Fallback: traditional polling-based REM worker
        from .workers.rem_worker import REMWorker

        rem_worker = REMWorker(
            handler=handler,
            episode_store=backends["episode_store"],
            interval_seconds=get_background_interval(),
            batch_size=get_background_batch_size(),
            min_episodes=get_background_min_episodes(),
            ontology_store=backends.get("ontology_store"),
            dragonfly=backends["dragonfly"],
        )
        tasks.append(rem_worker.run())
        logger.info("REM background worker enabled (polling mode)")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        if nats_client:
            await nats_client.close()
        await backends["dragonfly"].close()
        await backends["openai_client"].close()
        logger.info("Agent Memory Service stopped")


def cli():
    """CLI entrypoint."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
