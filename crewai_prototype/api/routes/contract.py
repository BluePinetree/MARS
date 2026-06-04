"""Contract discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1", tags=["contract"])

CONTRACT_PAYLOAD = {
    "version": "v1",
    "protocol": "sse",
    "official": True,
    "deprecated_protocols": ["websocket"],
    "endpoints": [
        "POST /api/v1/research",
        "GET /api/v1/research/{run_id}/status",
        "GET /api/v1/research/{run_id}/result",
        "GET /api/v1/research/{run_id}/stream",
        "GET /api/v1/research/{run_id}/artifacts/content",
        "GET /api/v1/research/{run_id}/artifacts/stream",
        "GET /api/v1/sessions",
        "GET /api/v1/sessions/{run_id}/logs",
        "DELETE /api/v1/sessions/{run_id}",
        "GET /api/v1/contract",
        "GET /api/v1/providers",
        "GET /api/v1/runtime-diagnostics",
    ],
}


@router.get("/contract")
def get_contract() -> dict:
    """Return the official API contract summary."""
    return CONTRACT_PAYLOAD


@router.get("/providers")
def get_providers() -> dict:
    """Return the currently available LLM providers."""
    try:
        from core.llm_factory import get_available_providers

        providers = get_available_providers()
    except Exception:
        providers = []
    return {"providers": providers}


@router.get("/runtime-diagnostics")
def get_runtime_diagnostics(request: Request) -> dict:
    """Return startup/runtime diagnostics."""
    import sys
    services = request.app.state.services
    return {
        "pipeline_version": "v3-crewai-native",
        "project_root": str(services.project_root),
        "output_root": str(services.output_root),
        "python_executable": sys.executable,
    }
