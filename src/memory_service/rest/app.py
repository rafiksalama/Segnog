"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import events, episodes, knowledge, artifacts, state, smart, pipelines, observe, ui
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
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
    app.include_router(ui.router, prefix=prefix, tags=["ui"])

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "agent-memory-service"}

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
