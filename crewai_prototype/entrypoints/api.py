"""API entrypoint for the V3 CrewAI-native research backend."""

from __future__ import annotations

import uvicorn

from api.app import create_app
from entrypoints.init import initialize_runtime

services = initialize_runtime()
app = create_app(services)


def run_api(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the FastAPI app with uvicorn."""
    uvicorn.run(app, host=host, port=port)

