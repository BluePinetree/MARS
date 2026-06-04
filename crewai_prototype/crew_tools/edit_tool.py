"""FileEditTool — diff-based file editing for CrewAI agents."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


def _resolve_safe(workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"Path escapes workspace: {relative_path}")
    return target


class _EditInput(BaseModel):
    workspace_root: str = Field(description="Absolute path to workspace root directory")
    relative_path: str = Field(description="File path relative to workspace root (e.g. 'src/data.py')")
    old_string: str = Field(description="Exact text to replace — must appear exactly once in the file")
    new_string: str = Field(description="Replacement text")

    @model_validator(mode="before")
    @classmethod
    def _unwrap_array(cls, data: Any) -> Any:
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return data


class FileEditTool(BaseTool):
    name: str = "FileEditTool"
    description: str = (
        "Edit a file by replacing old_string with new_string. "
        "Use this for targeted fixes instead of rewriting the whole file. "
        "Pass workspace_root, relative_path, old_string (exact match, must appear once), new_string. "
        "Returns 'OK: ...' on success, or 'ERROR: old_string not found' on failure — "
        "if it fails, read the file with WorkspaceReadTool and copy the exact text."
    )
    args_schema: Type[BaseModel] = _EditInput

    def _run(
        self, workspace_root: str, relative_path: str, old_string: str, new_string: str
    ) -> str:
        try:
            target = _resolve_safe(workspace_root, relative_path)
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not target.exists():
            return f"ERROR: File not found: {relative_path}"

        try:
            content = target.read_text(encoding="utf-8")
        except Exception as exc:
            return f"ERROR: Cannot read file: {exc}"

        if old_string not in content:
            return (
                f"ERROR: old_string not found in {relative_path}. "
                "Read the file with WorkspaceReadTool and copy the exact text including whitespace."
            )

        occurrences = content.count(old_string)
        if occurrences > 1:
            return (
                f"ERROR: old_string appears {occurrences} times in {relative_path}. "
                "Expand old_string to include more surrounding context to make it unique."
            )

        new_content = content.replace(old_string, new_string, 1)
        try:
            target.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return f"ERROR: Cannot write file: {exc}"

        return f"OK: replaced {len(old_string)} chars with {len(new_string)} chars in {relative_path}"
