"""Workspace read/write/list tools for LangGraph nodes (Anthropic tool schema)."""

from __future__ import annotations

from pathlib import Path


def _resolve(workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes workspace root: {relative_path}")
    return target


class WorkspaceReadTool:
    name = "workspace_read"
    description = "Read ONE file from the workspace. Returns full file content."

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_root": {"type": "string", "description": "Absolute path to workspace root"},
                    "relative_path": {"type": "string", "description": "File path relative to workspace root"},
                },
                "required": ["workspace_root", "relative_path"],
            },
        }

    def run(self, workspace_root: str, relative_path: str) -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            if not path.exists():
                return f"ERROR: File not found: {relative_path}"
            return path.read_text(encoding="utf-8")
        except Exception as e:
            return f"ERROR: {e}"


class WorkspaceWriteTool:
    name = "workspace_write"
    description = (
        "Write (or append) content to ONE file in the workspace. "
        "Use mode='write' (default) to create/overwrite. "
        "Use mode='append' to add to existing content — for files exceeding single response capacity."
    )

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_root": {"type": "string"},
                    "relative_path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["write", "append"],
                        "description": "write=overwrite (default), append=add to end",
                    },
                },
                "required": ["workspace_root", "relative_path", "content"],
            },
        }

    def run(self, workspace_root: str, relative_path: str, content: str, mode: str = "write") -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with path.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                path.write_text(content, encoding="utf-8")
            total_lines = len(path.read_text(encoding="utf-8").splitlines())
            return f"OK: {mode}d → {relative_path} ({total_lines} lines total)"
        except Exception as e:
            return f"ERROR: {e}"


class WorkspaceListTool:
    name = "workspace_list"
    description = "List files in the workspace directory. Use before reading/writing to confirm file existence."

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "workspace_root": {"type": "string"},
                    "directory": {
                        "type": "string",
                        "description": "Sub-directory to list (e.g. 'src/'). Empty = workspace root.",
                    },
                },
                "required": ["workspace_root"],
            },
        }

    def run(self, workspace_root: str, directory: str = "") -> str:
        try:
            root = Path(workspace_root).resolve()
            target = (root / directory).resolve() if directory else root
            try:
                target.relative_to(root)
            except ValueError:
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
        except Exception as e:
            return f"ERROR: {e}"
