"""Compute API-facing session and event payloads from stored runtime state."""

from __future__ import annotations

from core.api_contract import UISession, coerce_ui_log_event, compute_session_state, detect_architecture
from runtime.models import RunEvent, RunSession

DEFAULT_AGENTS = [
    "Research Planner",
    "Experiment Designer",
    "Code Generator",
    "Experiment Executor",
    "Result Analyzer",
    "Paper Writer",
]


class StateCalculator:
    """Map stored run state to the frontend-facing contract."""

    @staticmethod
    def _derive_status_for_events(session: RunSession, events: list[RunEvent]) -> str | None:
        """Allow persisted SYSTEM_END events to finalize a stale running session."""
        if session.is_terminal:
            return session.status
        if any(event.is_terminal_event for event in events):
            terminal_event = next((event for event in reversed(events) if event.is_terminal_event), None)
            if terminal_event is None:
                return None
            metadata = terminal_event.metadata if isinstance(terminal_event.metadata, dict) else {}
            raw_status = metadata.get("status")
            if raw_status:
                return str(raw_status)
            return "completed"
        return session.status

    def build_ui_event(self, event: RunEvent) -> dict:
        """Normalize a stored event to the canonical UI event shape."""
        return coerce_ui_log_event(
            event.to_dict(),
            default_session_id=event.session_id,
            default_run_id=event.run_id,
        ).model_dump()

    def build_ui_events(self, events: list[RunEvent]) -> list[dict]:
        """Normalize a list of stored events."""
        return [self.build_ui_event(event) for event in events]

    def build_ui_session(self, session: RunSession, events: list[RunEvent]) -> dict:
        """Normalize a stored session to the canonical UI session shape."""
        raw_events = [event.to_dict() for event in events]
        derived_active_status = self._derive_status_for_events(session, events)
        derived_state = compute_session_state(
            raw_events,
            active_status=derived_active_status,
            active_error=session.error,
            active_result_error=session.result_summary,
        )
        ui_session = UISession(
            run_id=session.run_id,
            session_id=session.session_id,
            research_topic=session.research_topic,
            architecture=detect_architecture(raw_events),
            status=derived_state["status"],
            progress=derived_state["progress"],
            start_time=session.started_at,
            end_time=derived_state.get("end_time") or session.ended_at,
            error_summary=derived_state.get("error_summary") or session.error,
            total_events=len(raw_events),
            agents=list(session.metadata.get("agents", DEFAULT_AGENTS)),
        )
        return ui_session.model_dump()
