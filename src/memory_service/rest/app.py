"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .routers import events, episodes, knowledge, artifacts, state, smart, pipelines, observe
from .dependencies import setup_backends, teardown_backends


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    await setup_backends(app)
    yield
    await teardown_backends(app)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Memory Service",
        description="General-purpose memory microservice for AI agent frameworks.",
        version="0.1.0",
        lifespan=lifespan,
    )

    prefix = "/api/v1/memory"

    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(episodes.router, prefix=prefix, tags=["episodes"])
    app.include_router(knowledge.router, prefix=prefix, tags=["knowledge"])
    app.include_router(artifacts.router, prefix=prefix, tags=["artifacts"])
    app.include_router(state.router, prefix=prefix, tags=["state"])
    app.include_router(smart.router, prefix=prefix, tags=["smart"])
    app.include_router(pipelines.router, prefix=prefix, tags=["pipelines"])
    app.include_router(observe.router, prefix=prefix, tags=["observe"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "agent-memory-service"}

    return app
