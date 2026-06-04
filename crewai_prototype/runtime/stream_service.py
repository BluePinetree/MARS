"""SSE stream helpers for run logs and artifact updates."""

from __future__ import annotations

import asyncio
import json

from runtime.event_store import EventStore
from runtime.run_repository import RunRepository
from runtime.session_store import SessionStore
from runtime.state_calculator import StateCalculator

TERMINAL_STATUSES = {"completed", "failed"}


class StreamService:
    """Tail session logs and artifacts as Server-Sent Events."""

    def __init__(
        self,
        session_store: SessionStore,
        event_store: EventStore,
        run_repository: RunRepository,
        state_calculator: StateCalculator,
        poll_interval: float = 1.0,
    ):
        self.session_store = session_store
        self.event_store = event_store
        self.run_repository = run_repository
        self.state_calculator = state_calculator
        self.poll_interval = poll_interval

    @staticmethod
    def _sse(event_name: str, payload: dict) -> str:
        """Encode a payload as an SSE frame."""
        return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _terminal_payload(run_id: str, session, event_count: int, artifact_count: int = 0) -> dict:
        """Build the canonical terminal SSE payload."""
        return {
            "run_id": run_id,
            "session_id": session.session_id,
            "status": session.status,
            "event_count": event_count,
            "artifact_count": artifact_count,
        }

    async def stream_logs(self, run_id: str):
        """Yield log SSE frames for the given run."""
        offset = 0
        while True:
            events = self.event_store.tail(run_id, offset)
            if events:
                for event in events:
                    yield self._sse("log", self.state_calculator.build_ui_event(event))
                offset += len(events)

            session = self.session_store.get(run_id)
            terminal_event_seen = self.event_store.has_terminal_event(run_id)
            if session and (session.status in TERMINAL_STATUSES or terminal_event_seen) and not events:
                yield self._sse("end", self._terminal_payload(run_id, session, offset))
                break
            await asyncio.sleep(self.poll_interval)

    async def stream_artifacts(self, run_id: str):
        """Yield artifact SSE frames for the given run."""
        seen_paths: set[str] = set()
        while True:
            artifacts = self.run_repository.list_artifacts(run_id)
            new_items = [artifact for artifact in artifacts if artifact.path not in seen_paths]
            for artifact in new_items:
                seen_paths.add(artifact.path)
                yield self._sse("artifact", artifact.to_dict())

            session = self.session_store.get(run_id)
            terminal_event_seen = self.event_store.has_terminal_event(run_id)
            if session and (session.status in TERMINAL_STATUSES or terminal_event_seen) and not new_items:
                yield self._sse(
                    "end",
                    self._terminal_payload(run_id, session, len(self.event_store.list(run_id)), len(seen_paths)),
                )
                break
            await asyncio.sleep(self.poll_interval)
