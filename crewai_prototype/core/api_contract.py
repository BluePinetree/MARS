"""UI-facing session and event contract types for the API layer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class UILogEvent(BaseModel):
    session_id: str = ""
    run_id: str = ""
    event_type: str = ""
    content: str = ""
    metadata: dict[str, Any] = {}
    agent_name: str | None = None
    timestamp: str | None = None


class UISession(BaseModel):
    run_id: str
    session_id: str
    research_topic: str = ""
    architecture: str = ""
    status: str = "queued"
    progress: int = 0
    start_time: str | None = None
    end_time: str | None = None
    error_summary: str | None = None
    total_events: int = 0
    agents: list[str] = []


def coerce_ui_log_event(
    event_dict: dict[str, Any],
    default_session_id: str = "",
    default_run_id: str = "",
) -> UILogEvent:
    return UILogEvent(
        session_id=event_dict.get("session_id") or default_session_id,
        run_id=event_dict.get("run_id") or default_run_id,
        event_type=event_dict.get("event_type", ""),
        content=str(event_dict.get("content", "")),
        metadata=event_dict.get("metadata") or {},
        agent_name=event_dict.get("agent_name"),
        timestamp=event_dict.get("timestamp"),
    )


def compute_session_state(
    raw_events: list[dict[str, Any]],
    active_status: str | None = None,
    active_error: str | None = None,
    active_result_error: str | None = None,
) -> dict[str, Any]:
    status = active_status or "queued"
    end_time = None
    error_summary = active_error

    agent_count = sum(1 for e in raw_events if e.get("event_type") == "AGENT_MESSAGE")
    total = max(len(raw_events), 1)
    progress = min(int(agent_count / total * 100), 99) if raw_events else 0

    terminal = next(
        (e for e in reversed(raw_events) if e.get("event_type") == "SYSTEM_END"),
        None,
    )
    if terminal:
        end_time = terminal.get("timestamp")
        progress = 100
        meta = terminal.get("metadata") or {}
        if not error_summary and meta.get("status") == "failed":
            error_summary = str(terminal.get("content", ""))

    return {
        "status": status,
        "progress": progress,
        "end_time": end_time,
        "error_summary": error_summary,
    }


def detect_architecture(raw_events: list[dict[str, Any]]) -> str:
    for event in raw_events:
        content = str(event.get("content", "")).lower()
        if "crewai" in content:
            return "CrewAI"
        if "autogen" in content:
            return "AutoGen"
        if "langgraph" in content:
            return "LangGraph"
    return "CrewAI"
