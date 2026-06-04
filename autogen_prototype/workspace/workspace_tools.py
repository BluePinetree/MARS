"""Workspace read/write/list tools — Anthropic + OpenAI schemas, AutoGen callable."""

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
                    "workspace_root": {"type": "string"},
                    "relative_path": {"type": "string"},
                },
                "required": ["workspace_root", "relative_path"],
            },
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string", "description": "Path relative to workspace root"},
                    },
                    "required": ["relative_path"],
                },
            },
        }

    def as_autogen_callable(self, workspace_root: str):
        """Return a workspace_root-bound callable for AutoGen FunctionTool."""
        tool = self

        def _workspace_read(relative_path: str) -> str:
            return tool.run(workspace_root, relative_path)

        _workspace_read.__name__ = self.name
        _workspace_read.__doc__ = self.description
        return _workspace_read

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
        "Use mode='append' to add to existing content."
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

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["write", "append"],
                        },
                    },
                    "required": ["relative_path", "content"],
                },
            },
        }

    def as_autogen_callable(self, workspace_root: str):
        tool = self

        def _workspace_write(relative_path: str, content: str, mode: str = "write") -> str:
            return tool.run(workspace_root, relative_path, content, mode)

        _workspace_write.__name__ = self.name
        _workspace_write.__doc__ = self.description
        return _workspace_write

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
    description = "List files in the workspace directory."

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

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Sub-directory to list. Empty = root."},
                    },
                    "required": [],
                },
            },
        }

    def as_autogen_callable(self, workspace_root: str):
        tool = self

        def _workspace_list(directory: str = "") -> str:
            return tool.run(workspace_root, directory)

        _workspace_list.__name__ = self.name
        _workspace_list.__doc__ = self.description
        return _workspace_list

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
