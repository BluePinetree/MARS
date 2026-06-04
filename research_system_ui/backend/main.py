"""Deprecated backend stub for the legacy research_system_ui service.

This module is kept read-only as a compatibility placeholder. The official
runtime is the crewai_prototype V2 /api/v1 SSE backend.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="research_system_ui legacy backend stub",
    description="Deprecated read-only stub. Use crewai_prototype /api/v1 SSE backend instead.",
    version="2.0.0",
)


@app.get("/")
def read_root() -> dict[str, str]:
    """Return the deprecation notice for the old UI backend."""
    return {
        "status": "deprecated",
        "message": "Read-only legacy stub. Use the crewai_prototype /api/v1 SSE backend instead of research_system_ui/backend.",
        "canonical_backend": "crewai_prototype /api/v1 SSE",
    }
