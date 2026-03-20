"""FastAPI application factory."""

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .routers import events, episodes, knowledge, artifacts, state, smart, pipelines, observe, ui
from .dependencies import setup_backends, teardown_backends
from ...workers.span_aggregator import run_span_aggregator

_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_API_PREFIX = "/api/v1/memory/"


class LatencyMiddleware(BaseHTTPMiddleware):
    """Record per-endpoint REST latency to DragonflyDB (fire-and-forget, non-blocking)."""

    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        path = request.url.path
        if path.startswith(_API_PREFIX) and hasattr(request.app.state, "dragonfly"):
            short = _UUID_RE.sub("/{id}", path[len(_API_PREFIX):]) or "/"
            endpoint = f"{request.method}:{short}"
            asyncio.create_task(
                request.app.state.dragonfly.record_latency(endpoint, duration_ms)
            )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    await setup_backends(app)
    # Start the span aggregator as a background task — reads timing:spans stream,
    # joins start/end pairs, and records per-step durations to the latency system.
    aggregator_task = asyncio.create_task(
        run_span_aggregator(app.state.dragonfly),
        name="span_aggregator",
    )
    try:
        yield
    finally:
        aggregator_task.cancel()
        await teardown_backends(app)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Memory Service",
        description=(
            "General-purpose memory microservice for AI agent frameworks. "
            "Provides episodic memory (observe/recall), knowledge graph, "
            "ontology entities, artifacts, and REM-cycle consolidation."
        ),
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/v1/memory/openapi.json",
        docs_url="/api/v1/memory/docs",
        redoc_url="/api/v1/memory/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LatencyMiddleware)

    prefix = "/api/v1/memory"

    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(episodes.router, prefix=prefix, tags=["episodes"])
    app.include_router(knowledge.router, prefix=prefix, tags=["knowledge"])
    app.include_router(artifacts.router, prefix=prefix, tags=["artifacts"])
    app.include_router(state.router, prefix=prefix, tags=["state"])
    app.include_router(smart.router, prefix=prefix, tags=["smart"])
    app.include_router(pipelines.router, prefix=prefix, tags=["pipelines"])
    app.include_router(observe.router, prefix=prefix, tags=["observe"])
    app.include_router(ui.router, prefix=prefix, tags=["ui"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "agent-memory-service"}

    @app.get("/api/v1/memory", include_in_schema=False)
    async def api_discovery():
        """Service discovery — returns links to OpenAPI spec and key endpoint groups."""
        return {
            "service": "agent-memory-service",
            "version": "0.1.0",
            "openapi": "/api/v1/memory/openapi.json",
            "docs": "/api/v1/memory/docs",
            "redoc": "/api/v1/memory/redoc",
            "endpoints": {
                "observe":    "POST /api/v1/memory/observe",
                "episodes":   "/api/v1/memory/episodes",
                "knowledge":  "/api/v1/memory/knowledge",
                "artifacts":  "/api/v1/memory/artifacts",
                "ontology":   "/api/v1/memory/ui/ontology",
                "smart":      "/api/v1/memory/smart",
                "pipelines":  "/api/v1/memory/pipelines",
                "health":     "/health",
            },
        }

    # Serve the built UI. In Docker the package is installed to site-packages so
    # we check a list of candidate paths rather than walking up from __file__.
    for _candidate in [
        Path("/app/ui/dist"),  # Docker
        Path(__file__).parent.parent.parent.parent / "ui" / "dist",  # editable install
    ]:
        if _candidate.exists():
            app.mount("/", StaticFiles(directory=str(_candidate), html=True), name="ui")
            break

    return app
