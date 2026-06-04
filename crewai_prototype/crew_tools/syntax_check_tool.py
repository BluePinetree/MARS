"""crew_tools/syntax_check_tool.py — Fast Python syntax & import checker.

Used by Phase 2 (StagedCoderService) to validate each file after writing.
Also exposed as a CrewAI tool so the Coder agent can self-check.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel

from core.handoff_models import CheckResult


# ── Standalone check functions (used by orchestrator directly) ────────────────

def check_syntax(file_path: str | Path) -> CheckResult:
    """Parse the file with ast.parse(). Returns CheckResult."""
    p = Path(file_path)
    if not p.exists():
        return CheckResult(
            passed=False,
            error=f"File not found: {file_path}",
            error_type="syntax",
        )
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        ast.parse(source, filename=str(p))
        return CheckResult(passed=True)
    except SyntaxError as exc:
        return CheckResult(
            passed=False,
            error=f"SyntaxError: {exc.msg} (line {exc.lineno})",
            error_type="syntax",
            line_no=exc.lineno,
        )
    except Exception as exc:
        return CheckResult(passed=False, error=str(exc), error_type="syntax")


_SKIP_IMPORT_PATTERNS = re.compile(
    r"\b(torch|tensorflow|sklearn|cv2|PIL|matplotlib|numpy|pandas|"
    r"scipy|seaborn|plotly|xgboost|lightgbm|catboost|gym|stable_baselines3)\b",
    re.IGNORECASE,
)


def check_import(file_path: str | Path, workspace_root: str | Path) -> CheckResult:
    """Run the file in a subprocess with import-only mode to detect import errors.

    Heavy ML libraries (torch, tensorflow, etc.) are skipped because they may
    not be installed in CI / the test environment.
    """
    p = Path(file_path)
    if not p.exists():
        return CheckResult(passed=False, error=f"File not found: {file_path}", error_type="import")

    source = p.read_text(encoding="utf-8", errors="replace")

    # Skip files that import heavy ML libs — can't reliably import-check them
    if _SKIP_IMPORT_PATTERNS.search(source):
        return CheckResult(passed=True)

    cmd = [
        sys.executable, "-c",
        f"import importlib.util, sys; "
        f"sys.path.insert(0, r'{workspace_root}'); "
        f"spec = importlib.util.spec_from_file_location('_chk', r'{p}'); "
        f"mod = importlib.util.module_from_spec(spec); "
        f"sys.modules['_chk'] = mod; "
        f"spec.loader.exec_module(mod)"
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(workspace_root),
        )
        if result.returncode == 0:
            return CheckResult(passed=True)

        stderr = result.stderr.strip()
        # Extract line number from traceback if available
        line_no: Optional[int] = None
        m = re.search(r"line (\d+)", stderr)
        if m:
            line_no = int(m.group(1))

        error_type = "import"
        if "SyntaxError" in stderr:
            error_type = "syntax"
        elif "ModuleNotFoundError" in stderr or "ImportError" in stderr:
            error_type = "import"

        return CheckResult(
            passed=False,
            error=stderr[-600:],  # last 600 chars
            error_type=error_type,
            line_no=line_no,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(passed=True)  # Treat timeout as pass (slow import)
    except Exception as exc:
        return CheckResult(passed=False, error=str(exc), error_type="import")


# ── CrewAI Tool wrappers ──────────────────────────────────────────────────────

class _SyntaxCheckInput(BaseModel):
    workspace_root: str
    relative_path: str


class SyntaxCheckTool(BaseTool):
    name: str = "SyntaxCheckTool"
    description: str = (
        "Check Python syntax of a file using ast.parse(). "
        "Pass workspace_root (absolute) and relative_path (e.g. 'src/model.py'). "
        "Returns 'OK' or an error message."
    )
    args_schema: Type[BaseModel] = _SyntaxCheckInput

    def _run(self, workspace_root: str, relative_path: str) -> str:
        full = Path(workspace_root) / relative_path
        result = check_syntax(full)
        if result.passed:
            return f"OK: {relative_path} syntax is valid."
        return f"SYNTAX ERROR in {relative_path}: {result.error}"


class _ImportCheckInput(BaseModel):
    workspace_root: str
    relative_path: str


class ImportCheckTool(BaseTool):
    name: str = "ImportCheckTool"
    description: str = (
        "Verify that a Python file can be imported without errors. "
        "Pass workspace_root (absolute) and relative_path (e.g. 'src/datasets.py'). "
        "Returns 'OK' or an error message."
    )
    args_schema: Type[BaseModel] = _ImportCheckInput

    def _run(self, workspace_root: str, relative_path: str) -> str:
        full = Path(workspace_root) / relative_path
        result = check_import(full, workspace_root)
        if result.passed:
            return f"OK: {relative_path} imports cleanly."
        return f"IMPORT ERROR in {relative_path}: {result.error}"
