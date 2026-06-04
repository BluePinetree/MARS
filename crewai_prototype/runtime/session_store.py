"""Session persistence for the V2 runtime."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.models import RunSession


class SessionStore:
    """Persist run session metadata as `session.json` files."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def run_path(self, run_id: str) -> Path:
        """Return the storage directory for a run."""
        return self.base_dir / run_id

    def session_path(self, run_id: str) -> Path:
        """Return the metadata file path for a run."""
        return self.run_path(run_id) / "session.json"

    @staticmethod
    def _write_json(path: Path, payload: Any, *, retries: int = 8, delay_seconds: float = 0.02) -> None:
        """Atomically write JSON content to a path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        last_error: OSError | None = None
        for attempt in range(retries):
            tmp_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                tmp_path.write_text(serialized, encoding="utf-8")
                tmp_path.replace(path)
                return
            except PermissionError as exc:
                last_error = exc
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
                if attempt == retries - 1:
                    raise
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error

    @staticmethod
    def _read_json(path: Path, *, retries: int = 5, delay_seconds: float = 0.02) -> Any:
        last_error: OSError | None = None
        for attempt in range(retries):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except PermissionError as exc:
                last_error = exc
                if attempt == retries - 1:
                    raise
                time.sleep(delay_seconds)
        if last_error is not None:
            raise last_error
        raise FileNotFoundError(path)

    def create(self, session: RunSession) -> None:
        """Create a new stored session record."""
        run_dir = self.run_path(session.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.session_path(session.run_id), session.to_dict())
        artifacts_path = run_dir / "artifacts.json"
        if not artifacts_path.exists():
            artifacts_path.write_text("[]", encoding="utf-8")

    def get(self, run_id: str) -> RunSession | None:
        """Return a stored session, if present."""
        path = self.session_path(run_id)
        if not path.exists():
            return None
        payload = self._read_json(path)
        return RunSession.from_dict(payload)

    def list(self) -> list[RunSession]:
        """List stored sessions ordered by newest first."""
        sessions: list[RunSession] = []
        for path in self.base_dir.glob("*/session.json"):
            try:
                payload = self._read_json(path)
                sessions.append(RunSession.from_dict(payload))
            except (OSError, ValueError, TypeError):
                continue
        sessions.sort(key=lambda s: s.started_at or '', reverse=True)
        return sessions

    def update(self, run_id: str, patch: dict[str, Any]) -> RunSession:
        """Merge and persist a patch into a session."""
        session = self.get(run_id)
        if session is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        payload = session.to_dict()
        payload.update({key: value for key, value in patch.items() if key != "metadata"})
        if isinstance(patch.get("metadata"), dict):
            merged_metadata = dict(payload.get("metadata") or {})
            merged_metadata.update(patch["metadata"])
            payload["metadata"] = merged_metadata
        updated = RunSession.from_dict(payload)
        self.create(updated)
        return updated

    def delete(self, run_id: str) -> bool:
        """Delete only the stored session metadata for the given run."""
        run_dir = self.run_path(run_id)
        if not run_dir.exists():
            return False
        path = run_dir / "session.json"
        if path.exists():
            path.unlink()
        try:
            next(run_dir.iterdir())
        except StopIteration:
            run_dir.rmdir()
        return True
