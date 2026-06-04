"""Run-level metadata and artifact persistence for the V2 runtime."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.models import ArtifactRecord
from runtime.session_store import SessionStore


class RunRepository:
    """Manage per-run metadata files beyond `session.json`."""

    def __init__(self, session_store: SessionStore):
        self.session_store = session_store

    def artifacts_path(self, run_id: str) -> Path:
        """Return the path to the stored artifact manifest."""
        path = self.session_store.run_path(run_id) / "artifacts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
        return path

    def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        """Load the stored artifacts for a run."""
        path = self.artifacts_path(run_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [ArtifactRecord.from_dict(item) for item in payload]

    def write_artifacts(self, run_id: str, artifacts: list[ArtifactRecord]) -> None:
        """Persist the complete artifact list for a run."""
        payload = [artifact.to_dict() for artifact in artifacts]
        self.artifacts_path(run_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_artifact(self, run_id: str, artifact: ArtifactRecord) -> None:
        """Append or replace a single artifact record."""
        artifacts = self.list_artifacts(run_id)
        deduped = [item for item in artifacts if item.path != artifact.path]
        deduped.append(artifact)
        self.write_artifacts(run_id, deduped)

