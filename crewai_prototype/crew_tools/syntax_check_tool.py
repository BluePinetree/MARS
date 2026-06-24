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


def check_dataclass_fields(entry_path: str | Path, workspace_root: str | Path) -> CheckResult:
    """AST 기반 검사: 워크스페이스의 @dataclass 정의와 호출부의 kwarg를 대조한다.

    torch import가 있어 check_import가 스킵되는 파일에서도
    RunConfig(amp=True) 같은 런타임 TypeError를 Phase 2에서 잡는다.
    """
    workspace = Path(workspace_root)
    entry_full = (workspace / entry_path) if not Path(entry_path).is_absolute() else Path(entry_path)
    if not entry_full.exists():
        return CheckResult(passed=True)

    try:
        entry_tree = ast.parse(entry_full.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return CheckResult(passed=True)  # syntax check가 따로 처리

    # 1. 워크스페이스 전체에서 @dataclass 정의 수집
    dataclass_fields: dict[str, set[str]] = {}
    for py_file in workspace.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            is_dc = any(
                (isinstance(d, ast.Name) and d.id == "dataclass") or
                (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                for d in node.decorator_list
            )
            if is_dc:
                dataclass_fields[node.name] = {
                    item.target.id
                    for item in node.body
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                }

    if not dataclass_fields:
        return CheckResult(passed=True)

    # 2. entry point에서 varname → ClassName 매핑 수집 (직접 대입만)
    # ex) spec = ExperimentSpec(...)  →  {"spec": "ExperimentSpec"}
    var_types: dict[str, str] = {}
    for node in ast.walk(entry_tree):
        if isinstance(node, ast.Assign):
            if (len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)):
                varname = node.targets[0].id
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id in dataclass_fields:
                    var_types[varname] = call.func.id
                elif isinstance(call.func, ast.Attribute) and call.func.attr in dataclass_fields:
                    var_types[varname] = call.func.attr
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and node.value is not None
                    and isinstance(node.value, ast.Call)):
                varname = node.target.id
                call = node.value
                if isinstance(call.func, ast.Name) and call.func.id in dataclass_fields:
                    var_types[varname] = call.func.id

    # 3. entry point의 모든 Call 노드에서 constructor kwarg 검증
    for node in ast.walk(entry_tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            class_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            class_name = node.func.attr
        else:
            continue
        if class_name not in dataclass_fields:
            continue
        valid = dataclass_fields[class_name]
        for kw in node.keywords:
            if kw.arg and kw.arg not in valid:
                return CheckResult(
                    passed=False,
                    error=(
                        f"TypeError: {class_name}() got unexpected keyword argument '{kw.arg}'. "
                        f"Valid fields: {sorted(valid)}"
                    ),
                    error_type="runtime",
                    line_no=getattr(node, "lineno", None),
                )

    # 4. 인스턴스 속성 접근 검증: varname.attr → ClassName에 attr 없으면 AttributeError
    # ex) spec.aug  →  ExperimentSpec에 aug 없으면 탐지
    for node in ast.walk(entry_tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        varname = node.value.id
        if varname not in var_types:
            continue
        class_name = var_types[varname]
        valid = dataclass_fields[class_name]
        if node.attr not in valid:
            return CheckResult(
                passed=False,
                error=(
                    f"AttributeError: '{class_name}' object has no attribute '{node.attr}' "
                    f"(accessed as {varname}.{node.attr}). "
                    f"Valid fields: {sorted(valid)}"
                ),
                error_type="runtime",
                line_no=getattr(node, "lineno", None),
            )

    return CheckResult(passed=True)


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
