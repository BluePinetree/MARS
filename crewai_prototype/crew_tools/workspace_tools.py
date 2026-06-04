"""Workspace file read/write/list tools for CrewAI agents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


def _resolve(workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"Path escapes workspace root: {relative_path}")
    return target


# ---------------------------------------------------------------------------
# Array-safe base: CrewAI's parser passes JSON arrays through unchanged
# (parser.py:181 skips json_repair for inputs that start/end with '['/']').
# This validator intercepts the array before Pydantic field validation and
# extracts the first element, so the tool receives a valid dict.
# ---------------------------------------------------------------------------

class _ArraySafeModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_array(cls, data: Any) -> Any:
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return data


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class _ReadInput(_ArraySafeModel):
    workspace_root: str = Field(description="Absolute path to the workspace root directory")
    relative_path: str = Field(description="File path relative to workspace root (e.g. 'src/data.py')")


class _WriteInput(_ArraySafeModel):
    workspace_root: str = Field(description="Absolute path to the workspace root directory")
    relative_path: str = Field(description="File path relative to workspace root (e.g. 'src/experiment_impl.py')")
    content: str = Field(description="Full file content to write")


class _ListInput(_ArraySafeModel):
    workspace_root: str = Field(description="Absolute path to the workspace root directory")
    directory: str = Field(default="", description="Sub-directory to list (e.g. 'src/'). Empty string = workspace root")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class WorkspaceReadTool(BaseTool):
    name: str = "WorkspaceReadTool"
    description: str = (
        "Read ONE file from the workspace. "
        "Pass a single dict with workspace_root and relative_path. "
        "NEVER pass a list or array — call this tool once per file."
    )
    args_schema: Type[BaseModel] = _ReadInput

    def _run(self, workspace_root: str, relative_path: str) -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            if not path.exists():
                return f"ERROR: File not found: {relative_path}"
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"ERROR: {exc}"


class WorkspaceWriteTool(BaseTool):
    name: str = "WorkspaceWriteTool"
    description: str = (
        "Write content to ONE file in the workspace. "
        "Pass a single dict with workspace_root, relative_path, and content. "
        "NEVER pass a list — call this tool once per file. "
        "Creates parent directories automatically."
    )
    args_schema: Type[BaseModel] = _WriteInput

    def _run(self, workspace_root: str, relative_path: str, content: str) -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            lines = content.count("\n") + 1
            return f"OK: wrote {lines} lines to {relative_path}"
        except Exception as exc:
            return f"ERROR: {exc}"


class WorkspaceListTool(BaseTool):
    name: str = "WorkspaceListTool"
    description: str = (
        "List files in the workspace directory. "
        "Use this to confirm which files already exist before reading or writing."
    )
    args_schema: Type[BaseModel] = _ListInput

    def _run(self, workspace_root: str, directory: str = "") -> str:
        try:
            root = Path(workspace_root).resolve()
            target = (root / directory).resolve() if directory else root
            if not str(target).startswith(str(root)):
                return "ERROR: directory escapes workspace root"
            if not target.exists():
                return f"ERROR: directory not found: {directory or '.'}"
            entries = sorted(target.rglob("*") if not directory else target.iterdir())
            lines = []
            for entry in entries:
                rel = entry.relative_to(root)
                marker = "/" if entry.is_dir() else ""
                lines.append(f"  {rel}{marker}")
            return "\n".join(lines) if lines else "(empty)"
        except Exception as exc:
            return f"ERROR: {exc}"
