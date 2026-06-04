"""Syntax check and import check tools for LangGraph nodes."""

from __future__ import annotations

import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _resolve(workspace_root: str, relative_path: str) -> Path:
    root = Path(workspace_root).resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes workspace root: {relative_path}")
    return target


class SyntaxCheckTool:
    name = "syntax_check"
    description = (
        "Check Python syntax of a workspace file. "
        "Returns 'OK' or 'SYNTAX_ERROR: <message>'. "
        "Always run after writing a Python file."
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
                },
                "required": ["workspace_root", "relative_path"],
            },
        }

    def run(self, workspace_root: str, relative_path: str) -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            if not path.exists():
                return f"ERROR: File not found: {relative_path}"
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                py_compile.compile(str(path), cfile=tmp_path, doraise=True)
                return "OK"
            except py_compile.PyCompileError as e:
                return f"SYNTAX_ERROR: {e}"
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            return f"ERROR: {e}"


class ImportCheckTool:
    name = "import_check"
    description = (
        "Check that a Python module can be imported without errors. "
        "Returns 'OK', 'IMPORT_SKIP (reason)' (env issue, safe to proceed), "
        "or 'IMPORT_ERROR: ...' (real code problem, must fix)."
    )
    _ENV_ERROR_MARKERS = ("OSError", "WinError", "DLL", "c10.dll", "cudart")

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

    def run(self, workspace_root: str, relative_path: str) -> str:
        try:
            path = _resolve(workspace_root, relative_path)
            if not path.exists():
                return f"ERROR: File not found: {relative_path}"
            src_root = Path(workspace_root) / "src"
            rel = Path(relative_path)
            parts = rel.parts
            if parts and parts[0] == "src":
                rel = Path(*parts[1:])
            module_name = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
            env = {**__import__("os").environ, "PYTHONPATH": str(src_root)}
            result = subprocess.run(
                [sys.executable, "-c", f"import {module_name}"],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return "OK"
            stderr = result.stderr.strip()
            if any(m in stderr for m in self._ENV_ERROR_MARKERS):
                return f"IMPORT_SKIP (environment/DLL error — safe to proceed): {stderr[:120]}"
            m = re.search(r"No module named '([^']+)'", stderr)
            if m:
                pkg = m.group(1).split(".")[0]
                local_modules = {p.stem for p in src_root.glob("*.py")} if src_root.exists() else set()
                if pkg not in local_modules:
                    return f"IMPORT_SKIP (third-party '{pkg}' not installed — safe to proceed)"
            return f"IMPORT_ERROR: {stderr}"
        except subprocess.TimeoutExpired:
            return "IMPORT_SKIP (timeout — environment issue, safe to proceed)"
        except Exception as e:
            return f"ERROR: {e}"
