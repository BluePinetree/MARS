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


def _is_dataclass_def(node: ast.ClassDef) -> bool:
    """ClassDef에 @dataclass 데코레이터가 붙어있는지 확인 (@dataclass, @dataclasses.dataclass,
    @dataclass(frozen=True) 등 Call 형태 포함)."""
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "dataclass":
            return True
    return False


def _collect_class_members(node: ast.ClassDef) -> set[str]:
    """dataclass의 유효한 속성 이름 집합을 수집한다.

    필드(AnnAssign / 기본값 Assign)뿐 아니라 **메서드/프로퍼티/클래스변수**도 포함한다.
    이를 빼먹으면 `mb.compute()` 같은 정상 메서드 접근이 '없는 필드'로 오탐된다.
    """
    members: set[str] = set()
    for item in node.body:
        # 타입 어노테이션 필드:  name: T [= default]
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            members.add(item.target.id)
        # 어노테이션 없는 클래스 변수:  name = default
        elif isinstance(item, ast.Assign):
            for tgt in item.targets:
                if isinstance(tgt, ast.Name):
                    members.add(tgt.id)
        # 메서드 / 프로퍼티 (def, async def)
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.add(item.name)
        # 중첩 클래스
        elif isinstance(item, ast.ClassDef):
            members.add(item.name)
    return members


def check_dataclass_fields(entry_path: str | Path, workspace_root: str | Path) -> CheckResult:
    """AST 기반 검사: 워크스페이스의 @dataclass 정의와 호출부의 kwarg를 대조한다.

    torch import가 있어 check_import가 스킵되는 파일에서도
    RunConfig(amp=True) 같은 런타임 TypeError를 Phase 2에서 잡는다.

    cross-module 동명 dataclass 오탐 방지:
    - 같은 이름의 @dataclass가 워크스페이스에 2개 이상 존재하면(예: metrics.py의 실제
      정의 + train_eval.py의 stub) 어느 정의가 바인딩됐는지 확정할 수 없으므로
      해당 이름은 필드/속성 검증에서 **보수적으로 제외**한다 (false positive 우선 방지).
    - 단, entry point가 실제로 특정 파일에서 그 이름을 import 한다면 그 정의로 확정해
      검증을 계속 수행한다 (진탐 유지).
    """
    workspace = Path(workspace_root)
    entry_full = (workspace / entry_path) if not Path(entry_path).is_absolute() else Path(entry_path)
    if not entry_full.exists():
        return CheckResult(passed=True)

    try:
        entry_tree = ast.parse(entry_full.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return CheckResult(passed=True)  # syntax check가 따로 처리

    # 1. 워크스페이스 전체에서 @dataclass 정의 수집.
    #    동명 충돌 감지를 위해 (파일경로, 멤버집합) 목록을 이름별로 모은다.
    per_name_defs: dict[str, list[tuple[Path, set[str]]]] = {}
    for py_file in workspace.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_dataclass_def(node):
                per_name_defs.setdefault(node.name, []).append(
                    (py_file.resolve(), _collect_class_members(node))
                )

    if not per_name_defs:
        return CheckResult(passed=True)

    # 1b. entry point의 import 문을 파싱해 "이름 → 바인딩된 정의 파일 stem" 힌트를 만든다.
    #     ex) `from metrics import MetricBundle` → imported_from["MetricBundle"] = "metrics"
    #     이 힌트로 동명 충돌을 해소할 수 있으면 검증을 유지한다.
    imported_from: dict[str, str] = {}
    for node in ast.walk(entry_tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod_stem = node.module.split(".")[-1]
            for alias in node.names:
                bound = alias.asname or alias.name
                imported_from[bound] = mod_stem

    # 1c. 이름별로 검증에 쓸 최종 멤버 집합을 확정한다.
    #     - 정의가 1개면 그대로 사용.
    #     - 정의가 2개 이상이면:
    #         * import 힌트로 파일이 특정되면 그 정의만 사용 (진탐 유지),
    #         * 그렇지 않으면 이 이름은 검증에서 제외 (오탐 방지).
    dataclass_fields: dict[str, set[str]] = {}
    for name, defs in per_name_defs.items():
        if len(defs) == 1:
            dataclass_fields[name] = defs[0][1]
            continue
        target_stem = imported_from.get(name)
        matched = [members for (path, members) in defs if path.stem == target_stem]
        if target_stem and len(matched) == 1:
            dataclass_fields[name] = matched[0]
        # else: 동명 충돌 미해소 → 보수적으로 검증 제외 (dataclass_fields에 넣지 않음)

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


# ── Cross-module 심볼·시그니처 게이트 (안정화: 시그니처 게이트) ──────────────────
# heavy-lib import로 check_import가 스킵되는 파일에서도, 워크스페이스 "내부" 함수의
#   (1) 미정의 심볼 import  (예: `from models import gbdt_impurity_importance` 미정의)
#   (2) 호출 arity 불일치    (예: `linear_coefficient_importance()` 필수 인자 0)
# 을 AST로 잡아 Phase 3 런타임 실패(→repair 루프)를 Phase 2에서 조기 차단한다.
# 오탐 방지 원칙(A1과 동일): 동명 다중정의·데코레이터·동적 인자(*args/**kwargs 스프레드)·
# 와일드카드 import 모듈은 보수적으로 제외한다. 이름 집합은 과수집(전체 트리)해 미정의 오탐을 막는다.

class _FuncSig:
    __slots__ = ("pos_names", "required", "max_pos", "has_vararg",
                 "has_kwarg", "kwonly_required", "decorated")

    def __init__(self, node: "ast.FunctionDef | ast.AsyncFunctionDef") -> None:
        a = node.args
        pos = list(getattr(a, "posonlyargs", [])) + list(a.args)
        self.pos_names = [p.arg for p in pos]
        self.required = len(pos) - len(a.defaults)
        self.has_vararg = a.vararg is not None
        self.has_kwarg = a.kwarg is not None
        self.max_pos = None if self.has_vararg else len(pos)
        self.kwonly_required = {
            ka.arg for ka, d in zip(a.kwonlyargs, a.kw_defaults) if d is None
        }
        self.decorated = bool(node.decorator_list)


def _assign_names(target) -> "list[str]":
    out: list[str] = []
    if isinstance(target, ast.Name):
        out.append(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for e in target.elts:
            out.extend(_assign_names(e))
    return out


def _collect_module_table(workspace: Path) -> dict:
    """워크스페이스 각 모듈(stem)의 top-level 함수 시그니처와 (과수집한) 이름 집합을 수집."""
    modules: dict[str, dict] = {}
    for py_file in workspace.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        entry = modules.setdefault(
            py_file.stem, {"names": set(), "funcs": {}, "wildcard": False}
        )
        # 함수 시그니처: 모듈 top-level만 (메서드/중첩 제외)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entry["funcs"].setdefault(node.name, []).append(_FuncSig(node))
        # 이름 집합: 전체 트리에서 과수집(미정의 오탐 방지 — 조건부/중첩 정의도 포함)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                entry["names"].add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    entry["names"].update(_assign_names(t))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                entry["names"].add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                if any(al.name == "*" for al in node.names):
                    entry["wildcard"] = True
                for al in node.names:
                    if al.name != "*":
                        entry["names"].add(al.asname or al.name)
            elif isinstance(node, ast.Import):
                for al in node.names:
                    entry["names"].add((al.asname or al.name).split(".")[0])
    return modules


def _resolve_callee_sig(func_node, imported, module_aliases, modules) -> "Optional[_FuncSig]":
    """호출 callee를 워크스페이스 함수 단일 정의로 해소(불가/모호 시 None)."""
    stem = orig = None
    if isinstance(func_node, ast.Name):
        if func_node.id in imported:
            stem, orig = imported[func_node.id]
    elif isinstance(func_node, ast.Attribute) and isinstance(func_node.value, ast.Name):
        if func_node.value.id in module_aliases:
            stem, orig = module_aliases[func_node.value.id], func_node.attr
    if stem is None or stem not in modules:
        return None
    sigs = modules[stem]["funcs"].get(orig)
    if not sigs or len(sigs) != 1:  # 미정의(함수 아님) 또는 동명 다중정의 → 보수적 제외
        return None
    return sigs[0]


def _check_call_arity(call: ast.Call, sig: "_FuncSig", has_dstar: bool) -> "Optional[str]":
    npos = len(call.args)
    kwnames = {kw.arg for kw in call.keywords if kw.arg}
    if sig.max_pos is not None and npos > sig.max_pos:
        return (f"too many positional arguments — call passes {npos}, "
                f"function accepts at most {sig.max_pos}")
    if npos < sig.required and not has_dstar:
        missing = [n for n in sig.pos_names[npos:sig.required] if n not in kwnames]
        if missing:
            return (f"missing required argument(s) {missing} "
                    f"(call passes {npos} positional, needs {sig.required})")
    if sig.kwonly_required and not has_dstar:
        miss_kw = sorted(sig.kwonly_required - kwnames)
        if miss_kw:
            return f"missing required keyword-only argument(s) {miss_kw}"
    return None


def check_cross_module_calls(entry_path: str | Path, workspace_root: str | Path) -> CheckResult:
    """워크스페이스 내부 함수의 미정의 import·호출 arity 불일치를 AST로 검증."""
    workspace = Path(workspace_root)
    modules = _collect_module_table(workspace)
    if not modules:
        return CheckResult(passed=True)
    local_stems = set(modules.keys())

    src_dir = workspace / "src"
    caller_root = src_dir if src_dir.is_dir() else workspace
    for py_file in caller_root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        imported: dict[str, tuple] = {}      # local_name -> (mod_stem, orig_name)
        module_aliases: dict[str, str] = {}  # alias -> mod_stem
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod_stem = node.module.split(".")[-1]
                if mod_stem not in local_stems:
                    continue
                mod = modules[mod_stem]
                for al in node.names:
                    if al.name == "*":
                        continue
                    # (1) 미정의 심볼 import — 와일드카드 재수출 모듈은 제외(오탐 방지)
                    if not mod["wildcard"] and al.name not in mod["names"]:
                        return CheckResult(
                            passed=False,
                            error=(f"ImportError: cannot import name '{al.name}' "
                                   f"from '{node.module}' (in {py_file.name}). "
                                   f"Defined: {sorted(mod['names'])[:25]}"),
                            error_type="import",
                            line_no=getattr(node, "lineno", None),
                        )
                    imported[al.asname or al.name] = (mod_stem, al.name)
            elif isinstance(node, ast.Import):
                for al in node.names:
                    top = al.name.split(".")[0]
                    if top in local_stems:
                        module_aliases[al.asname or top] = top

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue  # f(*args) → 정적 카운트 불가
            has_dstar = any(kw.arg is None for kw in node.keywords)
            sig = _resolve_callee_sig(node.func, imported, module_aliases, modules)
            if sig is None or sig.decorated:
                continue
            err = _check_call_arity(node, sig, has_dstar)
            if err:
                return CheckResult(
                    passed=False,
                    error=f"TypeError: {err} (in {py_file.name})",
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

    # 실행부(phase3 _run_script)는 PYTHONPATH에 <workspace>/src 를 넣는다.
    # import 검사도 동일하게 src/ 를 sys.path에 넣어야 `from artifacts import ...`
    # 같은 bare 절대 import가 실행 때와 동일하게 해석된다. src/ 누락 시 스캐폴드
    # main.py의 import가 spurious하게 실패해 파괴적 수리 루프를 유발한다.
    src_root = str(Path(workspace_root) / "src")
    cmd = [
        sys.executable, "-c",
        f"import importlib.util, sys; "
        f"sys.path.insert(0, r'{workspace_root}'); "
        f"sys.path.insert(0, r'{src_root}'); "
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
