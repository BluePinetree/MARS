from __future__ import annotations

import json
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class HandoffStore:
    """Framework-agnostic phase handoff persistence — no CrewAI/AutoGen imports."""

    def __init__(self, workspace_root: Path) -> None:
        self.handoff_dir = workspace_root / "handoff"
        self.handoff_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, model: BaseModel) -> Path:
        path = self.handoff_dir / f"{name}.json"
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, name: str, cls: Type[T]) -> T | None:
        path = self.handoff_dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            return None

    def load_raw(self, name: str) -> dict:
        path = self.handoff_dir / f"{name}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
