"""Session list and log routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

_MAX_EVENT_FILE_BYTES = 10 * 1024 * 1024  # 10 MB — skip bloated event files


@router.get("")
def list_sessions(request: Request, limit: int = 50) -> list[dict]:
    """List known sessions from the SessionStore (newest first, capped at limit)."""
    services = request.app.state.services
    sessions = []
    for session in services.session_store.list()[:limit]:
        event_path: Path = services.event_store.event_path(session.run_id)
        if event_path.exists() and event_path.stat().st_size > _MAX_EVENT_FILE_BYTES:
            events = []
        else:
            events = services.event_store.list(session.run_id)
        sessions.append(services.state_calculator.build_ui_session(session, events))
    return sessions


@router.get("/{run_id}/logs")
def get_session_logs(run_id: str, request: Request) -> list[dict]:
    """Return normalized log events for a session."""
    services = request.app.state.services
    session = services.session_store.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    events = services.event_store.list(run_id)
    return services.state_calculator.build_ui_events(events)


@router.delete("/{run_id}")
def delete_session(run_id: str, request: Request) -> dict[str, bool]:
    """Delete only the V2 metadata owned by the SessionStore."""
    services = request.app.state.services
    deleted = services.session_store.delete(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return {"deleted": True}

