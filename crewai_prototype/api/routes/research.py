"""Research run routes (V4 pipeline)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas import ResearchCreateResponse, ResearchRequest

router = APIRouter(prefix="/api/v1/research", tags=["research"])


@router.post("")
async def create_research_run(
    payload: ResearchRequest,
    request: Request,
) -> ResearchCreateResponse:
    """Create and schedule a V4 research run."""
    services = request.app.state.services
    try:
        prepared = services.coordinator.prepare_run(payload.to_coordinator_input())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        services.coordinator.launch_prepared(prepared)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ResearchCreateResponse(
        run_id=prepared.session.run_id,
        session_id=prepared.session.session_id,
        status=prepared.session.status,
    )


@router.get("/{run_id}/status")
def get_research_status(run_id: str, request: Request) -> dict:
    """Return the normalized status payload for a research run."""
    services = request.app.state.services
    session = services.session_store.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    events = services.event_store.list(run_id)
    return services.state_calculator.build_ui_session(session, events)


@router.get("/{run_id}/result")
def get_research_result(run_id: str, request: Request) -> dict:
    """Return a compact summary of the final run result."""
    services = request.app.state.services
    session = services.session_store.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return {
        "run_id": run_id,
        "status": session.status,
        "output_path": session.output_path,
        "result_summary": session.result_summary,
        "error": session.error,
    }


@router.get("/{run_id}/stream")
async def stream_research_logs(run_id: str, request: Request) -> StreamingResponse:
    """Stream normalized log events as SSE."""
    services = request.app.state.services
    if services.session_store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return StreamingResponse(
        services.stream_service.stream_logs(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
