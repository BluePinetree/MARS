"""Event persistence for the V2 runtime."""

from __future__ import annotations

import json
import time
from pathlib import Path

from runtime.models import RunEvent

# Roll over the file when it exceeds this size; keep the most recent lines.
_MAX_EVENT_FILE_BYTES = 5 * 1024 * 1024   # 5 MB
_TRIM_KEEP_LINES = 3000


class EventStore:
    """Persist run events as newline-delimited JSON."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # run_id -> (last_file_byte_offset, cached_events)
        self._cache: dict[str, tuple[int, list[RunEvent]]] = {}

    def event_path(self, run_id: str) -> Path:
        """Return the event log path for a run."""
        path = self.base_dir / run_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _trim_if_needed(self, run_id: str, path: Path) -> None:
        """5MB 초과 시 오래된 줄을 events_archive_<ts>.jsonl 로 이동하고 최근 줄만 유지.

        삭제 대신 아카이브하므로 사후 디버깅이 가능하다.
        """
        try:
            if path.stat().st_size <= _MAX_EVENT_FILE_BYTES:
                return
            lines = path.read_bytes().splitlines()
            if len(lines) <= _TRIM_KEEP_LINES:
                return
            archived = lines[:-_TRIM_KEEP_LINES]
            kept = lines[-_TRIM_KEEP_LINES:]
            # 아카이브 파일: events_archive_<unix_ms>.jsonl
            ts = int(time.time() * 1000)
            archive_path = path.parent / f"events_archive_{ts}.jsonl"
            archive_path.write_bytes(b"\n".join(archived) + b"\n")
            path.write_bytes(b"\n".join(kept) + b"\n")
            self.invalidate(run_id)
        except Exception:
            pass

    def append(self, run_id: str, event: RunEvent) -> None:
        """Append an event to the run log."""
        path = self.event_path(run_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
            handle.write("\n")
        self._trim_if_needed(run_id, path)

    def append_many(self, run_id: str, events: list[RunEvent]) -> None:
        """Append multiple events to the run log."""
        if not events:
            return
        path = self.event_path(run_id)
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
                handle.write("\n")
        self._trim_if_needed(run_id, path)

    def list(self, run_id: str) -> list[RunEvent]:
        """Return all stored events for a run, using incremental file reads."""
        path = self.event_path(run_id)
        if not path.exists():
            return []

        current_size = path.stat().st_size
        cached_offset, cached_events = self._cache.get(run_id, (0, []))

        if current_size == cached_offset:
            return cached_events

        new_events: list[RunEvent] = []
        with path.open("rb") as f:
            f.seek(cached_offset)
            new_bytes = f.read()

        for line in new_bytes.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                new_events.append(RunEvent.from_dict(json.loads(line)))
            except (ValueError, TypeError):
                continue

        all_events = cached_events + new_events
        self._cache[run_id] = (current_size, all_events)
        return all_events

    def invalidate(self, run_id: str) -> None:
        """Evict the cache entry for a run (e.g. after external truncation)."""
        self._cache.pop(run_id, None)

    def last(self, run_id: str) -> RunEvent | None:
        """Return the latest stored event for a run."""
        events = self.list(run_id)
        if not events:
            return None
        return events[-1]

    def has_terminal_event(self, run_id: str) -> bool:
        """Return True when a SYSTEM_END event has been persisted."""
        return any(event.is_terminal_event for event in self.list(run_id))

    def tail(self, run_id: str, offset: int = 0) -> list[RunEvent]:
        """Return events after the given offset."""
        events = self.list(run_id)
        return events[max(0, offset):]
