"""phases/phase2_coding.py — Staged coding with direct LLM content generation.

이전 구현은 CrewAI 에이전트가 WorkspaceWriteTool을 호출해서 파일을 쓰는 방식이었다.
CrewAI 1.x native function calling 환경에서 LLM이 도구를 호출하는 대신 텍스트를 반환하면
파일이 디스크에 쓰이지 않고 "File not found" 에러가 발생하는 구조적 문제가 있었다.

새 구현:
  - LLM에게 파일 내용을 텍스트로 생성하도록 직접 호출
  - Python 코드가 디스크에 파일 쓰기를 보장 (도구 호출 의존성 제거)
  - 수정(repair)도 동일 방식으로 처리

Write loop per file:
  1. LLM → 파일 내용 생성 (직접 호출, 도구 없음)
  2. Python → 디스크에 파일 쓰기 (보장됨)
  3. 구문 + import 검사
  4. 실패 시 → LLM이 현재 내용 + 에러 보고 수정 (최대 MAX_AUTO_REPAIR_ATTEMPTS)
  5. 여전히 실패 시 → USER_GUIDANCE_NEEDED 에스컬레이션
  6. 사용자 힌트 → 재시도; "skip" → 최소 stub 작성
"""

from __future__ import annotations

import ast
import logging
import textwrap
from pathlib import Path
from typing import Callable, Optional

from core.handoff_models import (
    CheckResult,
    CodingResult,
    FileNodeSpec,
    FileResult,
    PlanBundle,
    RepairRecord,
    StageCodingResult,
)
from core.llm_factory import create_llm_for_agent
from crew_tools.syntax_check_tool import check_dataclass_fields, check_import, check_syntax
from orchestration.approval_registry import CancellationToken, GuidanceRegistry
from pipeline_config.constants import (
    MAX_AUTO_REPAIR_ATTEMPTS,
    USER_GUIDANCE_TIMEOUT_SECS,
)

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]

# 의존성 파일을 컨텍스트로 포함할 때의 크기 상한
_MAX_DEP_CHARS = 6_000    # 파일 1개당
_MAX_TOTAL_DEP_CHARS = 18_000  # 전체 합산


# ── 텍스트 유틸 ────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """마크다운 코드 펜스(```python ... ``` 또는 ``` ... ```)를 제거한다."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    start = 1
    end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
    return "\n".join(lines[start:end])


def _emit_check_error(emit: EmitFn, file_path: str, check, attempt: int) -> None:
    """검사 실패를 적절한 이벤트 타입으로 발행한다."""
    error_type = getattr(check, "error_type", "") or ""
    event_type = "FILE_IMPORT_ERROR" if error_type == "import" else "FILE_SYNTAX_ERROR"
    emit(
        event_type,
        f"[Coder] {file_path}: {check.error[:120]}",
        {"file_path": file_path, "error": check.error, "attempt": attempt},
    )


def _ensure_init_files(directory: Path, workspace_root: Path) -> None:
    """src/ 하위 서브디렉토리에 __init__.py가 없으면 빈 파일로 생성한다."""
    try:
        rel = directory.relative_to(workspace_root)
    except ValueError:
        return
    if rel == Path("."):
        return
    current = workspace_root
    for part in rel.parts:
        current = current / part
        init = current / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def _write_to_disk(relative_path: str, workspace_root: str, content: str) -> None:
    """내용을 workspace에 쓴다. 부모 디렉토리와 __init__.py를 자동으로 생성한다."""
    full = Path(workspace_root) / relative_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    if full.suffix == ".py":
        _ensure_init_files(full.parent, Path(workspace_root))


# ── 파괴적 수리 회귀 가드 (public API shrink 탐지) ────────────────────────────

def _is_public_name(name: str) -> bool:
    """public 심볼 여부. `_`로 시작하면 비공개.

    dunder(`__x__`)는 통상 프레임워크 훅(예: `__init__`, `__call__`)이지 공개
    API 표면이 아니므로 축소 판단 대상에서 제외한다(상식선).
    """
    if name.startswith("__") and name.endswith("__"):
        return False
    return not name.startswith("_")


def _public_symbol_set(source: str) -> set[str]:
    """소스에 정의된 public 심볼 집합을 AST로 추출한다 (순수 함수).

    반환 항목:
      - 모듈 레벨 public 함수:         "func"
      - 모듈 레벨 public 클래스:        "Class"
      - public 클래스의 public 메서드:  "Class.method"

    비공개(`_`로 시작)나 dunder는 제외. 파싱 실패(SyntaxError) 시 빈 집합을
    반환한다 — 파싱 불가한 소스는 "정의된 심볼 없음"으로 취급해, 깨진 코드를
    고치는 정상 수리가 이 가드에 걸리지 않도록 한다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    symbols: set[str] = set()
    _def = (ast.FunctionDef, ast.AsyncFunctionDef)

    for node in tree.body:
        if isinstance(node, _def):
            if _is_public_name(node.name):
                symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            if not _is_public_name(node.name):
                continue
            symbols.add(node.name)
            for child in node.body:
                if isinstance(child, _def) and _is_public_name(child.name):
                    symbols.add(f"{node.name}.{child.name}")
    return symbols


def _is_noop_body(node) -> bool:
    """함수/메서드 본문이 사실상 no-op(스텁)인지 판정한다.

    다음만으로 구성된 본문을 스텁으로 본다:
      - docstring / 상수 표현식 (ast.Expr[Constant])
      - `pass`
      - `...` (Ellipsis)
      - `raise NotImplementedError(...)`
      - `return`(값 없음) 또는 `return None`
    """
    for stmt in node.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring 또는 `...`
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            name = None
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                name = exc.func.id
            elif isinstance(exc, ast.Name):
                name = exc.id
            if name == "NotImplementedError":
                continue
            return False
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                continue
            if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                continue
            return False
        return False
    return True


def _noop_symbol_set(source: str) -> set[str]:
    """소스에서 본문이 no-op(스텁)인 public 함수/메서드 심볼 집합을 추출한다.

    `_public_symbol_set`과 동일한 이름 규칙을 쓰되, 본문이 `_is_noop_body`인
    항목만 담는다. 클래스 자체는 (본문 판정이 무의미하므로) 포함하지 않는다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    noops: set[str] = set()
    _def = (ast.FunctionDef, ast.AsyncFunctionDef)

    for node in tree.body:
        if isinstance(node, _def):
            if _is_public_name(node.name) and _is_noop_body(node):
                noops.add(node.name)
        elif isinstance(node, ast.ClassDef):
            if not _is_public_name(node.name):
                continue
            for child in node.body:
                if isinstance(child, _def) and _is_public_name(child.name) and _is_noop_body(child):
                    noops.add(f"{node.name}.{child.name}")
    return noops


def _detect_api_shrink(before: str, after: str) -> set[str]:
    """수리 전→후 소스에서 public API가 삭제·축소된 심볼 집합을 반환한다.

    "축소"의 두 형태:
      1) 삭제: before에 있던 public 심볼이 after에 없다.
      2) 스텁화: before에서 실체가 있던 public 함수/메서드가 after에서
         no-op 스텁(pass / ... / return None / raise NotImplementedError)으로
         후퇴했다. (예: MetricBundle.compute()의 본문 제거)

    빈 집합이면 축소 없음(정상 수리). before가 파싱 불가하면(원본이 이미 깨짐)
    비교 기준이 없으므로 빈 집합을 반환해 정상 수리를 막지 않는다.
    """
    before_syms = _public_symbol_set(before)
    if not before_syms:
        return set()  # 원본에 비교할 public 정의가 없음 → 가드 비적용

    after_syms = _public_symbol_set(after)

    # (1) 삭제된 public 심볼
    removed = before_syms - after_syms

    # (2) 실체 → no-op 스텁으로 후퇴한 심볼
    before_noops = _noop_symbol_set(before)
    after_noops = _noop_symbol_set(after)
    # before에서 실체가 있던(=노옵 아님) & after에도 존재하지만 now no-op
    shrunk = {
        sym for sym in after_noops
        if sym in before_syms and sym not in before_noops
    }

    return removed | shrunk


def _extract_api_surface(source: str) -> str:
    """함수/클래스 시그니처 + 첫 번째 docstring만 추출한다.

    imports, __all__, def/class 시그니처, docstring만 남기고 구현 본문은 제거.
    AST 파싱 실패(SyntaxError) 시 원본을 그대로 반환한다.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    lines = source.splitlines()
    out: list[str] = []

    def _include(start: int, end: int) -> None:
        out.extend(lines[start - 1 : end])

    def _process_def(node) -> None:
        sig_start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        if not node.body:
            _include(sig_start, node.end_lineno)
            return

        body_first = node.body[0]
        sig_end = max(sig_start, body_first.lineno - 1)
        _include(sig_start, sig_end)

        if (
            isinstance(body_first, ast.Expr)
            and isinstance(body_first.value, ast.Constant)
            and isinstance(body_first.value.value, str)
        ):
            _include(body_first.lineno, body_first.end_lineno)
            rest = node.body[1:]
        else:
            rest = node.body

        out.append("")

        if isinstance(node, ast.ClassDef):
            for child in rest:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _process_def(child)
                    out.append("")

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            _include(node.lineno, node.end_lineno)
        elif isinstance(node, ast.Assign):
            if any(ast.unparse(t) == "__all__" for t in node.targets):
                _include(node.lineno, node.end_lineno)
                out.append("")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _process_def(node)

    return "\n".join(out)


def _build_dep_context(imports_from: list[str], workspace_root: str) -> str:
    """이미 작성된 의존성 파일들의 API 시그니처를 컨텍스트 문자열로 반환한다."""
    sections: list[str] = []
    total = 0
    for dep_path in imports_from:
        full = Path(workspace_root) / dep_path
        if not full.exists():
            continue
        raw = full.read_text(encoding="utf-8", errors="replace")
        api = _extract_api_surface(raw)
        if len(api) > _MAX_DEP_CHARS:
            api = api[:_MAX_DEP_CHARS] + "\n# ... (TRUNCATED)"
        sections.append(f"# === {dep_path} ===\n{api}")
        total += len(api)
        if total >= _MAX_TOTAL_DEP_CHARS:
            break
    return "\n\n".join(sections)


# ── 직접 LLM 호출 ──────────────────────────────────────────────────────────────

def _generate_content(
    file_spec: FileNodeSpec,
    workspace_root: str,
    stack_rule: str,
    extra_context: str,
    llm,
) -> str:
    """LLM을 직접 호출해 새 파일의 완전한 Python 소스를 생성한다."""
    deps = _build_dep_context(file_spec.imports_from, workspace_root)

    parts = [
        f"Write the complete Python implementation for: {file_spec.path}",
        "",
        f"Responsibility: {file_spec.responsibility}",
        f"Must export (define these symbols): {', '.join(file_spec.exports) or '(see responsibility)'}",
        f"Stack rule: {stack_rule}",
        f"Research context: {extra_context}",
    ]
    if file_spec.path.endswith("experiment_impl.py"):
        parts += [
            "",
            "SCAFFOLD CONTRACT (this file is invoked by the stable src/main.py — obey exactly):",
            "- Expose `run_selected_experiments(args, runtime_context)` and `run_single_experiment(...)`.",
            "- `runtime_context` (a config_schema.RuntimeContext) provides: output_root (Path),",
            "  results_root (Path), seed (int), epochs (int), batch_size (int), device (str),",
            "  data_root (Path|None). Use runtime_context.seed for reproducibility.",
            "- `run_selected_experiments` MUST run the experiment(s) and RETURN a dict that contains a",
            "  `metrics` object of NUMERIC results, e.g. {\"metrics\": {\"accuracy\": 0.83, \"roc_auc\": 0.86}}.",
            "  For model comparisons, include each model's scores under `metrics` (e.g. per-model keys).",
            "- Do NOT call sys.exit(), do NOT write results/result.json, and do NOT define main() —",
            "  the stable src/main.py parses args and writes results/result.json from your returned dict.",
        ]
    if deps:
        parts += [
            "",
            "Workspace dependencies (already written; your imports must match their actual exports):",
            deps,
        ]
    parts += [
        "",
        "IMPORT RULES (strictly enforced):",
        "- NEVER use relative imports (e.g. `from . import X`, `from .module import X`).",
        "  The workspace root is on sys.path; use absolute imports: `from module import X`.",
        "- For files inside subdirectories (e.g. src/models/resnet.py importing src/utils.py),",
        "  import as: `from utils import X`  (NOT `from ..utils import X`).",
        "",
        "DATASET RULES:",
        "- For any dataset download (CIFAR-10, ImageNet, etc.), use",
        "  `os.environ.get('DATA_DIR', './data')` as the root/cache directory.",
        "  This directory is persistent across runs — only download if files are missing.",
        "",
        "Output ONLY valid Python source code.",
        "Do NOT include markdown fences, prose, or explanations.",
    ]

    raw = llm.call([{"role": "user", "content": "\n".join(parts)}])
    if not isinstance(raw, str):
        raw = str(raw)
    return _strip_fences(raw)


_NO_API_SHRINK_RULE = (
    "CRITICAL — DO NOT REMOVE OR STUB PUBLIC API:\n"
    "You MUST keep every existing public function, class, and public method\n"
    "(names not starting with '_'). Do NOT delete them and do NOT reduce their\n"
    "bodies to a no-op (pass / ... / return None / raise NotImplementedError).\n"
    "Fix the actual syntax/import error while PRESERVING all existing behavior.\n"
    "If a checker complains about a symbol, correct it — never remove the symbol."
)


def _repair_content(
    file_path: str,
    workspace_root: str,
    error_msg: str,
    hint: str,
    llm,
    attempt: int = 1,
    extra_rule: str = "",
) -> str:
    """LLM을 직접 호출해 검사 오류가 있는 파일의 수정 버전을 생성한다.

    attempt <= 1: 이전 코드를 포함해 LLM이 수정 방향을 파악하도록 한다.
    attempt >= 2: 이전 코드를 제외하고 spec 기반으로 재생성 — 같은 실수 반복 방지.
    """
    parts = [
        "Repair this Python file so it passes syntax and import checks.",
        "",
        f"File: {file_path}",
        f"Error:\n{error_msg}",
    ]
    if hint:
        parts += ["", f"Hint from user: {hint}"]

    if attempt <= 1:
        current = (Path(workspace_root) / file_path).read_text(encoding="utf-8", errors="replace")
        parts += [
            "",
            "Current (broken) content — fix this:",
            current,
        ]
    else:
        parts += [
            "",
            "(Previous attempt also failed with the same or similar error."
            " Rewrite the file from scratch based only on the error message and file path.)",
        ]

    parts += [
        "",
        "IMPORT RULE: NEVER use relative imports (`from . import X` or `from .mod import X`).",
        "Use absolute imports only: `from module import X`.",
    ]
    if extra_rule:
        parts += ["", extra_rule]
    parts += [
        "",
        "Output ONLY the corrected Python source. No markdown fences. No explanation.",
    ]

    raw = llm.call([{"role": "user", "content": "\n".join(parts)}])
    if not isinstance(raw, str):
        raw = str(raw)
    return _strip_fences(raw)


# ── 검사 파이프라인 ────────────────────────────────────────────────────────────

def _run_checks(file_path: str, workspace_root: str) -> CheckResult:
    """구문 → import → dataclass 필드 검사. 첫 번째 실패 또는 통과를 반환한다."""
    full = Path(workspace_root) / file_path
    syntax = check_syntax(full)
    if not syntax.passed:
        return syntax
    import_check = check_import(full, workspace_root)
    if not import_check.passed:
        return import_check
    return check_dataclass_fields(file_path, workspace_root)


def _apply_repair_guarded(
    target_path: str,
    workspace_root: str,
    error_msg: str,
    hint: str,
    llm,
    attempt: int,
    emit: EmitFn,
) -> bool:
    """수리 결과를 회귀 가드를 거쳐 디스크에 적용한다.

    동작:
      1. 수리 전 소스를 읽어 둔다(before). 파일이 없으면 before="".
      2. `_repair_content`로 수리본을 생성.
      3. `_detect_api_shrink(before, after)`로 public API 삭제·축소 검사.
      4. 축소 감지 시:
         - 이번 수리본을 반려(디스크에 쓰지 않음)하고,
         - `_NO_API_SHRINK_RULE`을 프롬프트에 추가해 1회 재생성 시도.
         - 재생성본도 축소하면 최종 반려 → 원본(before)을 유지(파일 미변경).
         - `REPAIR_REJECTED_API_SHRINK` 이벤트로 로깅.
      5. 축소 없으면 디스크에 기록.

    반환: 새 내용을 실제로 디스크에 썼으면 True, 원본을 유지했으면 False.
    LLM 호출 예외는 상위 루프가 처리하도록 그대로 전파한다.
    """
    full = Path(workspace_root) / target_path
    before = full.read_text(encoding="utf-8", errors="replace") if full.exists() else ""

    content = _repair_content(target_path, workspace_root, error_msg, hint, llm, attempt=attempt)
    shrunk = _detect_api_shrink(before, content)

    if not shrunk:
        _write_to_disk(target_path, workspace_root, content)
        return True

    # ── 반려 1: 축소 감지 → 강경 규칙 붙여 재생성 ────────────────────────────
    emit(
        "REPAIR_REJECTED_API_SHRINK",
        f"[Coder] Repair for {target_path} rejected — would remove/stub public API: "
        f"{', '.join(sorted(shrunk))[:200]}. Retrying with API-preservation rule.",
        {
            "file_path": target_path,
            "attempt": attempt,
            "shrunk_symbols": sorted(shrunk),
            "stage": "retry",
        },
    )

    retry = _repair_content(
        target_path, workspace_root, error_msg, hint, llm,
        attempt=attempt, extra_rule=_NO_API_SHRINK_RULE,
    )
    retry_shrunk = _detect_api_shrink(before, retry)

    if not retry_shrunk:
        _write_to_disk(target_path, workspace_root, retry)
        return True

    # ── 반려 2(최종): 재생성도 축소 → 원본 유지 ──────────────────────────────
    emit(
        "REPAIR_REJECTED_API_SHRINK",
        f"[Coder] Repair for {target_path} rejected again — keeping original to avoid "
        f"destructive repair. Symbols at risk: {', '.join(sorted(retry_shrunk))[:200]}.",
        {
            "file_path": target_path,
            "attempt": attempt,
            "shrunk_symbols": sorted(retry_shrunk),
            "stage": "kept_original",
        },
    )
    return False


# ── 수정 루프 ──────────────────────────────────────────────────────────────────

def _repair_loop(
    file_spec: FileNodeSpec,
    workspace_root: str,
    run_id: str,
    llm,
    guidance_registry: GuidanceRegistry,
    emit: EmitFn,
    cancel: Optional[CancellationToken],
    stack_rule: str,
    extra_context: str,
) -> FileResult:
    """파일을 생성하고 검사를 통과할 때까지 수정한다.

    직접 LLM 호출로 내용을 생성하고, Python 코드가 디스크에 씀.
    CrewAI 도구 호출에 의존하지 않으므로 파일이 반드시 쓰인다.
    """
    from orchestration.approval_registry import GuidanceGate

    file_path = file_spec.path

    # ── 초기 생성 ─────────────────────────────────────────────────────────────
    emit(
        "AGENT_MESSAGE",
        f"[Coder] Generating {file_path} …",
        {"file": file_path},
    )
    try:
        content = _generate_content(file_spec, workspace_root, stack_rule, extra_context, llm)
        _write_to_disk(file_path, workspace_root, content)
    except Exception as exc:
        logger.warning("Initial generation failed for %s: %s", file_path, exc)
        _write_stub(file_path, workspace_root, file_spec.responsibility)

    check = _run_checks(file_path, workspace_root)
    if check.passed:
        emit(
            "FILE_GENERATED",
            f"[Coder] {file_path} written and verified.",
            {"file_path": file_path, "stage": file_spec.stage},
        )
        return FileResult(path=file_path, written=True, check=check)

    # 첫 번째 검사 실패 → 에러 이벤트 발행
    _emit_check_error(emit, file_path, check, attempt=0)

    # ── 수정 루프 ─────────────────────────────────────────────────────────────
    repair_records: list[RepairRecord] = []
    attempt = 0
    hint = ""
    error_msg = check.error

    while True:
        if cancel and cancel.is_cancelled:
            logger.info("Repair loop cancelled for %s", file_path)
            return FileResult(
                path=file_path, written=True,
                check=CheckResult(passed=False, error="Cancelled"),
                repair_records=repair_records,
            )

        attempt += 1
        emit(
            "AGENT_MESSAGE",
            f"[Coder] Repairing {file_path} (attempt {attempt}) — {error_msg[:120]}",
            {"file": file_path, "attempt": attempt, "error": error_msg},
        )

        try:
            _apply_repair_guarded(
                file_path, workspace_root, error_msg, hint, llm, attempt, emit
            )
        except Exception as exc:
            logger.warning("Repair LLM call failed for %s (attempt %d): %s", file_path, attempt, exc)

        new_check = _run_checks(file_path, workspace_root)
        record = RepairRecord(
            attempt=attempt,
            error_before=error_msg,
            passed=new_check.passed,
            user_hint=hint,
        )
        repair_records.append(record)
        hint = ""  # hint 소비

        if new_check.passed:
            emit(
                "FILE_FIXED",
                f"[Coder] {file_path} repaired after {attempt} attempt(s).",
                {"file_path": file_path, "attempt": attempt},
            )
            return FileResult(
                path=file_path, written=True, check=new_check,
                repair_records=repair_records,
            )

        error_msg = new_check.error
        _emit_check_error(emit, file_path, new_check, attempt=attempt)

        if attempt < MAX_AUTO_REPAIR_ATTEMPTS:
            continue

        # ── 사용자 에스컬레이션 ───────────────────────────────────────────────
        gate = GuidanceGate(
            file_path=file_path,
            error_msg=error_msg,
            attempt_count=attempt,
        )
        guidance_registry.register(run_id, file_path, gate)

        emit(
            "USER_GUIDANCE_NEEDED",
            f"[Coder] Cannot auto-fix {file_path} after {attempt} attempts. "
            f"Waiting for your guidance.",
            {
                "run_id": run_id,
                "entry": file_path,
                "diagnosis": f"Syntax/import check failed after {attempt} auto-repair attempts.",
                "error": error_msg,
                "attempts": attempt,
                "options": ["continue", "skip", "provide_fix", "manual_edit"],
            },
        )

        resolved = gate.wait(timeout=USER_GUIDANCE_TIMEOUT_SECS)
        guidance_registry.remove(run_id, file_path)

        if not resolved:
            emit(
                "AGENT_MESSAGE",
                f"[Coder] Guidance timeout for {file_path} — continuing auto-repair.",
                {"file": file_path, "timeout": True},
            )
            attempt = 0
            continue

        emit(
            "USER_GUIDANCE_RECEIVED",
            f"[Coder] User action for {file_path}: {gate.user_action}",
            {"file": file_path, "action": gate.user_action, "hint": gate.hint},
        )

        if gate.should_skip:
            _write_stub(file_path, workspace_root, file_spec.responsibility)
            emit(
                "AGENT_MESSAGE",
                f"[Coder] {file_path} skipped by user — minimal stub written.",
                {"file": file_path, "stubbed": True},
            )
            return FileResult(
                path=file_path, written=True,
                check=CheckResult(passed=True),
                repair_records=repair_records,
                escalated_to_user=True,
            )

        if gate.user_action == "manual_edit":
            new_check = _run_checks(file_path, workspace_root)
            if new_check.passed:
                emit(
                    "AGENT_MESSAGE",
                    f"[Coder] {file_path} passed after manual edit.",
                    {"file": file_path, "manual_edit": True},
                )
                return FileResult(
                    path=file_path, written=True, check=new_check,
                    repair_records=repair_records, escalated_to_user=True,
                )
            error_msg = new_check.error

        # "continue" 또는 "provide_fix" — hint 주입 후 카운터 리셋
        hint = gate.hint or ""
        attempt = 0


def _write_stub(file_path: str, workspace_root: str, responsibility: str) -> None:
    """파싱은 가능한 최소 placeholder stub을 작성한다."""
    stub = textwrap.dedent(f"""\
        \"\"\"STUB: {file_path} — {responsibility or 'placeholder'}

        자동 코드 생성 중 건너뛴 파일.
        실험 실행 전 실제 구현으로 교체하세요.
        \"\"\"
        # TODO: implement {file_path}
    """)
    full = Path(workspace_root) / file_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(stub, encoding="utf-8")


# ── 단계별 코딩 오케스트레이션 ────────────────────────────────────────────────

def run_coding_phase(
    plan: PlanBundle,
    guidance_registry: GuidanceRegistry,
    emit: EmitFn,
    llm=None,
    cancel: Optional[CancellationToken] = None,
) -> CodingResult:
    """계획의 모든 mutable 파일에 대해 단계별 코딩을 실행한다.

    Stage 1 → 2 → 3 순서로, 각 파일은 의존성 순서대로 처리한다.
    전체 단계 완료 후 integration smoke test를 수행한다.
    """
    llm = create_llm_for_agent("code_generator")

    workspace_root = plan.workspace.workspace_dir
    run_id = plan.workspace.run_id

    profile = plan.planner.recommended_profile or "generic_script"
    stack_rule = _STACK_RULES.get(profile, _STACK_RULES["generic_script"])

    extra_context = (
        f"Research goal: {plan.planner.problem_statement}\n"
        f"Success criteria: {'; '.join(plan.planner.success_criteria[:3])}"
    )

    stage_map: dict[int, list[FileNodeSpec]] = {1: [], 2: [], 3: []}
    for f in plan.designer.files:
        if f.mutable:
            stage_map[f.stage].append(f)

    ordered_paths = plan.designer.generation_order or [f.path for f in plan.designer.files]
    for stage_num in (1, 2, 3):
        stage_map[stage_num].sort(
            key=lambda f: ordered_paths.index(f.path) if f.path in ordered_paths else 999
        )

    coding_result = CodingResult()

    total_files = sum(len(stage_map[s]) for s in (1, 2, 3))
    files_done = 0

    for stage_num in (1, 2, 3):
        files = stage_map[stage_num]
        if not files:
            continue

        emit(
            "PHASE_START",
            f"[Phase 2] Stage {stage_num} — {len(files)} file(s)",
            {"stage": stage_num, "files": [f.path for f in files]},
        )

        stage_result = StageCodingResult(stage=stage_num)

        for file_spec in files:
            if cancel and cancel.is_cancelled:
                break

            # Stage 3 파일은 Stage 1 전체를 dep context에 강제 포함
            # (Designer가 imports_from을 누락하거나 예산 초과로 드롭되어도 dataclass API 보장)
            if stage_num == 3:
                stage1_written = [
                    fr.path
                    for s in coding_result.stages
                    if s.stage == 1
                    for fr in s.files
                    if fr.written
                ]
                extra = [p for p in stage1_written if p not in file_spec.imports_from]
                if extra:
                    file_spec = file_spec.model_copy(
                        update={"imports_from": file_spec.imports_from + extra}
                    )

            file_result = _repair_loop(
                file_spec=file_spec,
                workspace_root=workspace_root,
                run_id=run_id,
                llm=llm,
                guidance_registry=guidance_registry,
                emit=emit,
                cancel=cancel,
                stack_rule=stack_rule,
                extra_context=extra_context,
            )
            stage_result.files.append(file_result)
            files_done += 1
            if total_files > 0:
                ratio = files_done / total_files
                emit(
                    "token_budget_snapshot",
                    f"[TokenBudget] {files_done}/{total_files} files ({ratio:.0%})",
                    {"used": files_done, "budget": total_files, "ratio": ratio,
                     "label": f"Stage {stage_num}: {file_spec.path}"},
                )

        coding_result.stages.append(stage_result)
        emit(
            "AGENT_MESSAGE",
            f"[Phase 2] Stage {stage_num} complete. Passed: {stage_result.all_passed}",
            {"stage": stage_num, "passed": stage_result.all_passed},
        )

    coding_result = _run_smoke_test(
        plan=plan,
        coding_result=coding_result,
        guidance_registry=guidance_registry,
        emit=emit,
        cancel=cancel,
        llm=llm,
    )

    return coding_result


def _generate_entry_point(
    plan: PlanBundle,
    coding_result: CodingResult,
    workspace_root: str,
    llm,
) -> str:
    """생성된 파일들을 바탕으로 실제 실험을 실행하는 엔트리포인트를 생성한다.

    - results/result.json에 metrics를 저장해야 함 (Phase 4 Writer가 읽음).
    - Stage 1 파일 실제 내용을 프롬프트에 포함해 LLM이 실제 클래스/함수 시그니처를 사용하도록 한다.
    """
    results_dir = str(Path(workspace_root) / "results")

    # 생성된 파일 목록 및 각 파일의 책임 수집
    file_specs_by_path = {f.path: f for f in plan.designer.files}
    written_paths = [
        fr.path
        for stage in coding_result.stages
        for fr in stage.files
        if fr.written
    ]

    file_summaries = []
    for p in written_paths:
        spec = file_specs_by_path.get(p)
        if spec:
            exports = ", ".join(spec.exports[:5]) if spec.exports else "see file"
            file_summaries.append(f"  {p}: {spec.responsibility[:80]} (exports: {exports})")
        else:
            file_summaries.append(f"  {p}")

    # Stage 1 파일 실제 내용 수집 (DataConfig 등 핵심 API 시그니처 포함)
    stage1_paths = [
        fr.path
        for stage in coding_result.stages
        if stage.stage == 1
        for fr in stage.files
        if fr.written
    ]
    dep_context = _build_dep_context(stage1_paths, workspace_root)

    profile = plan.planner.recommended_profile or "generic_script"
    stack_rule = _STACK_RULES.get(profile, _STACK_RULES["generic_script"])

    entry = plan.designer.entry_point or "src/main.py"
    # Strip leading "src/" to compute import-relative path from src/
    # e.g. "src/exp/model.py" → "exp.model" (importable from within src/)
    def _to_import_path(file_path: str) -> str:
        p = file_path.replace("\\", "/")
        if p.startswith("src/"):
            p = p[4:]
        return p.replace("/", ".").removesuffix(".py")

    import_examples = []
    for fp in written_paths[:5]:
        spec = file_specs_by_path.get(fp)
        imp = _to_import_path(fp)
        if spec and spec.exports:
            import_examples.append(f"  from {imp} import {spec.exports[0]}")
        else:
            import_examples.append(f"  import {imp}")

    prompt_parts = [
        f"Write a complete Python entry point script: {entry}",
        "",
        f"Research goal: {plan.planner.problem_statement}",
        f"Success criteria: {'; '.join(plan.planner.success_criteria[:3])}",
        f"Stack: {stack_rule}",
        "",
        "CRITICAL IMPORT RULE:",
        f"  This script lives at {entry} and is run as:",
        f"    python {entry}   (cwd = workspace root)",
        "  Python adds the script's directory (src/) to sys.path automatically.",
        "  Therefore, import workspace modules WITHOUT 'src.' prefix:",
        "    CORRECT:   from exp.model import ResNet18",
        "    INCORRECT: from src.exp.model import ResNet18  ← ModuleNotFoundError!",
        "",
        "Already-written workspace files (import from these):",
        *file_summaries,
    ]

    if dep_context:
        prompt_parts += [
            "",
            "STAGE 1 FILE CONTENTS — actual class/function definitions.",
            "Use ONLY the constructors and signatures shown below.",
            "Do NOT add parameters that are not in these definitions.",
            dep_context,
        ]

    prompt_parts += [
        "",
        "Import examples (correct form):",
        *import_examples,
        "",
        "Requirements:",
        "1. Import workspace modules WITHOUT 'src.' prefix (see rule above).",
        "2. Run the full experiment end-to-end (load data, train, evaluate).",
        "3. Collect metrics (accuracy, loss, etc.) as a dict.",
        f"4. Save metrics to: {results_dir}/result.json",
        '   Format: {"metrics": {"metric_name": value, ...}, "success": true}',
        "5. Print progress to stdout so Phase 3 can stream it.",
        "6. Add `if __name__ == '__main__': main()` at the bottom.",
        "",
        "Output ONLY valid Python source. No markdown, no explanation.",
    ]

    prompt = "\n".join(prompt_parts)

    raw = llm.call([{"role": "user", "content": prompt}])
    if not isinstance(raw, str):
        raw = str(raw)
    return _strip_fences(raw)


def _run_smoke_test(
    plan: PlanBundle,
    coding_result: CodingResult,
    guidance_registry: GuidanceRegistry,
    emit: EmitFn,
    cancel: Optional[CancellationToken],
    llm=None,
) -> CodingResult:
    """entry point에 대한 빠른 구문/import smoke test.

    전체 실험을 실행하지 않고 entry point를 파싱 및 import 가능한지만 확인한다.
    실패 시 실제로 _repair_content()를 호출해 수정 — time.sleep 재확인 루프가 아님.
    """
    import time
    from pipeline_config.constants import MAX_SMOKE_TOTAL_SECS

    entry = plan.designer.entry_point or "src/main.py"
    workspace_root = plan.workspace.workspace_dir
    run_id = plan.workspace.run_id

    # 스캐폴드가 소유하는 안정 파일 — 수리/재생성 대상에서 제외한다.
    # 이들을 LLM이 수정하면 import 에러를 experiment_impl 스텁화로 "게이밍"해
    # 실제 구현을 무력화하는 specification-gaming 실패가 발생한다.
    _STABLE_SCAFFOLD = {
        "src/main.py", "src/cli.py", "src/artifacts.py",
        "src/config_schema.py", "src/metrics.py",
    }
    entry_is_stable = entry in _STABLE_SCAFFOLD
    # 안정 entry(main.py)의 import 실패는 실제로 mutable 모듈에서 비롯되므로
    # 수리는 experiment_impl.py를 대상으로 한다.
    repair_target = "src/experiment_impl.py" if entry_is_stable else entry

    emit("AGENT_MESSAGE", f"[Phase 2] Smoke test: checking {entry}", {"entry": entry})

    # 엔트리포인트 파일이 아예 없으면 먼저 생성 시도 (단, 안정 스캐폴드 파일은 LLM 재생성 금지)
    entry_full = Path(workspace_root) / entry
    if not entry_full.exists():
        if entry_is_stable:
            emit(
                "AGENT_MESSAGE",
                f"[Phase 2] Stable entry {entry} missing — scaffold should provide it; skipping LLM generation",
                {"entry": entry, "stable": True},
            )
        else:
            emit("AGENT_MESSAGE", f"[Phase 2] Entry point missing — generating {entry}", {"entry": entry})
            try:
                content = _generate_entry_point(plan, coding_result, workspace_root, llm)
                _write_to_disk(entry, workspace_root, content)
            except Exception as exc:
                logger.warning("Entry point generation failed: %s", exc)

    check = _run_checks(entry, workspace_root)
    if check.passed:
        coding_result.smoke_test_passed = True
        emit("SMOKE_TEST_DONE", "[Phase 2] Smoke test passed.", {"passed": True, "entry": entry})
        return coding_result

    coding_result.smoke_test_error = check.error
    smoke_attempt = 0
    hint = ""
    deadline = time.monotonic() + MAX_SMOKE_TOTAL_SECS

    while True:
        if cancel and cancel.is_cancelled:
            break

        if time.monotonic() > deadline:
            emit(
                "AGENT_MESSAGE",
                f"[Phase 2] Smoke test timed out after {MAX_SMOKE_TOTAL_SECS}s.",
                {"smoke_test": "timeout"},
            )
            break

        smoke_attempt += 1

        if smoke_attempt > MAX_AUTO_REPAIR_ATTEMPTS:
            from orchestration.approval_registry import GuidanceGate
            gate = GuidanceGate(
                file_path=entry,
                error_msg=check.error,
                attempt_count=smoke_attempt,
            )
            guidance_registry.register(run_id, entry, gate)
            emit(
                "USER_GUIDANCE_NEEDED",
                f"[Phase 2] Smoke test cannot be fixed automatically after {smoke_attempt} attempts.",
                {
                    "run_id": run_id,
                    "file": entry,
                    "error": check.error,
                    "attempts": smoke_attempt,
                    "options": ["continue", "skip"],
                },
            )
            resolved = gate.wait(timeout=USER_GUIDANCE_TIMEOUT_SECS)
            guidance_registry.remove(run_id, entry)
            if not resolved or gate.should_skip:
                break
            hint = gate.hint or ""
            smoke_attempt = 0
            continue

        # 실제 repair 호출 (단순 재확인 루프가 아님).
        # 안정 entry(main.py)는 절대 덮어쓰지 않고 mutable 모듈(experiment_impl.py)을 수리한다.
        target_full = Path(workspace_root) / repair_target
        if entry_is_stable and not target_full.exists():
            emit(
                "AGENT_MESSAGE",
                f"[Phase 2] Smoke repair target {repair_target} missing — cannot repair without stubbing stable entry.",
                {"repair_target": repair_target},
            )
        else:
            try:
                _apply_repair_guarded(
                    repair_target, workspace_root, check.error, hint, llm, smoke_attempt, emit
                )
            except Exception as exc:
                logger.warning("Smoke test repair failed (attempt %d): %s", smoke_attempt, exc)

        hint = ""  # hint 소비
        check = _run_checks(entry, workspace_root)

        if check.passed:
            coding_result.smoke_test_passed = True
            coding_result.smoke_test_error = ""
            emit("SMOKE_TEST_DONE", "[Phase 2] Smoke test passed after repair.",
                 {"passed": True, "entry": entry, "repair_attempts": smoke_attempt})
            break

        coding_result.smoke_test_error = check.error
        emit(
            "AGENT_MESSAGE",
            f"[Phase 2] Smoke test repair attempt {smoke_attempt} failed: {check.error[:80]}",
            {"smoke_attempt": smoke_attempt, "error": check.error},
        )

    if not coding_result.smoke_test_passed:
        emit("SMOKE_TEST_DONE", "[Phase 2] Smoke test could not be resolved.",
             {"passed": False, "entry": entry, "error": coding_result.smoke_test_error})

    return coding_result


# ── 스택 규칙 (프로파일별) ────────────────────────────────────────────────────

_STACK_RULES: dict[str, str] = {
    "vision_classification": (
        "PyTorch only. Use torchvision for datasets. No TensorFlow. "
        "Models: ResNet, ViT, or EfficientNet. Use torch.nn, torch.optim."
    ),
    "tabular_supervised": (
        "scikit-learn or XGBoost/LightGBM. Pandas for data loading. "
        "No deep learning frameworks unless explicitly requested."
    ),
    "timeseries_forecasting": (
        "PyTorch or statsmodels. Use pandas for time series. "
        "Models: LSTM, Transformer, or ARIMA family."
    ),
    "generic_script": (
        "Use standard Python libraries. PyTorch or scikit-learn if ML is needed. "
        "No framework-specific assumptions."
    ),
}
