"""FastAPI app factory for the V4 pipeline."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.artifacts import router as artifacts_router
from api.routes.interaction import router as interaction_router
from api.routes.research import router as research_router
from api.routes.sessions import router as sessions_router


def create_app(services) -> FastAPI:
    """Create the FastAPI app and attach initialized services."""
    app = FastAPI(
        title="Research System V4",
        description="Multi-agent research pipeline — no circuit breaker, always escalates",
        version="4.0.0",
    )
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(research_router)
    app.include_router(interaction_router)
    app.include_router(artifacts_router)
    app.include_router(sessions_router)
    return app

