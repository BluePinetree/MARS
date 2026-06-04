"""orchestration/checkpoint_manager.py — Phase-level checkpoint persistence.

Phase 완료 시점마다 저장하고, 크래시 후 재시작 시 복원해 처음부터 다시 실행하지 않도록 한다.
injection_queue.json은 checkpoint.json과 항상 동시에 저장한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CHECKPOINT_FILE = "checkpoint.json"
_QUEUE_FILE = "injection_queue.json"


class CheckpointManager:
    """Saves and restores per-run phase checkpoints to survive crashes."""

    def __init__(self, output_base: str = "outputs") -> None:
        self._base = Path(output_base)

    def _dir(self, run_id: str) -> Path:
        return self._base / run_id

    def save(
        self,
        run_id: str,
        phase: int,
        completed_files: list[str],
        injection_queue: list,
    ) -> None:
        """Write checkpoint + injection queue atomically (tmp → rename)."""
        d = self._dir(run_id)
        d.mkdir(parents=True, exist_ok=True)

        data = {
            "run_id": run_id,
            "phase": phase,
            "completed_files": completed_files,
        }
        tmp = d / (_CHECKPOINT_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(d / _CHECKPOINT_FILE)

        q_tmp = d / (_QUEUE_FILE + ".tmp")
        q_tmp.write_text(json.dumps(injection_queue, indent=2), encoding="utf-8")
        q_tmp.replace(d / _QUEUE_FILE)

        logger.debug(
            "Checkpoint saved: run=%s phase=%d files=%d", run_id, phase, len(completed_files)
        )

    def load(self, run_id: str) -> Optional[dict]:
        """Return checkpoint dict or None if no checkpoint exists."""
        path = self._dir(run_id) / _CHECKPOINT_FILE
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not read checkpoint for %s — starting fresh.", run_id)
            return None

    def load_queue(self, run_id: str) -> list:
        """Return persisted injection queue or empty list."""
        path = self._dir(run_id) / _QUEUE_FILE
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def clear(self, run_id: str) -> None:
        """Remove checkpoint files for a completed or cleared run."""
        d = self._dir(run_id)
        for name in (_CHECKPOINT_FILE, _QUEUE_FILE):
            p = d / name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        logger.debug("Checkpoint cleared for run=%s", run_id)
