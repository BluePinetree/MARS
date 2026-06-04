"""Artifact routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

router = APIRouter(prefix="/api/v1/research/{run_id}/artifacts", tags=["artifacts"])


@router.get("/content")
def get_artifact_content(
    run_id: str,
    request: Request,
    path: str = Query(..., description="Artifact path to read"),
) -> PlainTextResponse:
    """Return the text content for a tracked artifact."""
    services = request.app.state.services
    session = services.session_store.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    artifact_path = Path(path)
    if not artifact_path.is_absolute():
        artifact_path = Path(session.output_path or services.output_root) / artifact_path
    resolved = artifact_path.resolve()
    allowed_root = Path(session.output_path or services.output_root).resolve()
    if allowed_root not in resolved.parents and resolved != allowed_root:
        raise HTTPException(status_code=400, detail="Artifact path is outside the run output directory")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return PlainTextResponse(resolved.read_text(encoding="utf-8", errors="replace"))


@router.get("/stream")
async def stream_artifacts(run_id: str, request: Request) -> StreamingResponse:
    """Stream artifact updates as SSE."""
    services = request.app.state.services
    if services.session_store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return StreamingResponse(
        services.stream_service.stream_artifacts(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

