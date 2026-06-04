"""
Local context store for compact run memory.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class LocalContextStore:
    """Manage project shared memory and run-scoped compact state."""

    def __init__(self, run_output_dir: Path, project_root: Path):
        self.run_output_dir = run_output_dir
        self.project_root = project_root
        self.context_dir = run_output_dir / "context"
        self.context_dir.mkdir(parents=True, exist_ok=True)

        self.shared_memory_path = project_root / "CLAUDE.md"
        self.runtime_memory_path = self.context_dir / "runtime_memory.md"
        self.handoff_state_path = self.context_dir / "handoff_state.json"
        self.compact_history_path = self.context_dir / "compact_history.md"

        if not self.runtime_memory_path.exists():
            self.runtime_memory_path.write_text(
                "# Runtime Context\n\n",
                encoding="utf-8",
            )
        if not self.handoff_state_path.exists():
            self.handoff_state_path.write_text(
                json.dumps({}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if not self.compact_history_path.exists():
            self.compact_history_path.write_text(
                "# Compact History\n\n",
                encoding="utf-8",
            )

    def load_shared_memory(self, max_chars: int = 4000) -> str:
        if not self.shared_memory_path.exists():
            return ""
        text = self.shared_memory_path.read_text(encoding="utf-8", errors="ignore")
        return text[:max_chars]

    def load_runtime_memory(self, max_chars: int = 2000) -> str:
        if not self.runtime_memory_path.exists():
            return ""
        text = self.runtime_memory_path.read_text(encoding="utf-8", errors="ignore")
        return text[-max_chars:]

    def append_runtime_memory(self, title: str, content: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.runtime_memory_path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {title} ({now})\n\n{content.strip()}\n")

    def save_handoff_state(self, state: Dict[str, Any]) -> None:
        self.handoff_state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_handoff_state(self) -> Dict[str, Any]:
        if not self.handoff_state_path.exists():
            return {}
        try:
            return json.loads(self.handoff_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def append_compact_record(
        self,
        title: str,
        original_chars: int,
        compact_chars: int,
        note: str,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.compact_history_path.open("a", encoding="utf-8") as f:
            f.write(
                f"\n## {title} ({now})\n"
                f"- original_chars: {original_chars}\n"
                f"- compact_chars: {compact_chars}\n"
                f"- note: {note.strip()}\n"
            )

    def clear_runtime_context(self) -> None:
        self.runtime_memory_path.write_text(
            "# Runtime Context\n\nCleared.\n",
            encoding="utf-8",
        )
        self.handoff_state_path.write_text(
            json.dumps({}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.compact_history_path.write_text(
            "# Compact History\n\nCleared.\n",
            encoding="utf-8",
        )

