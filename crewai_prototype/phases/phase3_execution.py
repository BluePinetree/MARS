"""phases/phase3_execution.py — Experiment execution (Phase 3).

Runs the entry-point script in the workspace, collects results, and applies
the same escalation pattern as Phase 2 — no silent failures.

Flow:
  1. ExecutorAgent runs entry_point via RunCommandTool
  2. Reads results/result.json via ReadResultTool
  3. If failed: AnalyzerAgent diagnoses → CoderAgent repairs → retry
  4. After MAX_EXEC_REPAIR_ATTEMPTS: escalate to user (same GuidanceGate)
  5. Never gives up unless user says "skip"
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from crewai import Agent, Crew, Task

from core.handoff_models import (
    CodingResult,
    ExecutorResult,
    PlanBundle,
)
from core.json_extractor import extract_json_object as extract_json
from core.llm_factory import create_llm_for_agent
from crew_tools import RunCommandTool, ReadResultTool, WorkspaceReadTool
from orchestration.approval_registry import CancellationToken, GuidanceRegistry
from pipeline_config.constants import (
    DATA_CACHE_DIR,
    EXPERIMENT_TIMEOUT_SECS,
    EXECUTOR_MAX_ITER,
    MAX_EXEC_REPAIR_ATTEMPTS,
    USER_GUIDANCE_TIMEOUT_SECS,
)

logger = logging.getLogger(__name__)
EmitFn = Callable[[str, str, Optional[dict]], None]


# ── Task descriptions ─────────────────────────────────────────────────────────

_EXEC_TASK = """\
Workspace root: {workspace_root}
Entry point:    {entry_point}
Timeout:        {timeout}s

Run the experiment:
1. Call RunCommandTool with:
   command="python {entry_point}"
   working_dir="{workspace_root}"
   timeout={timeout}
2. If return_code == 0, call ReadResultTool to read "results/result.json".
3. Report the exact return_code and any metric values from result.json.
4. If return_code != 0, report the stderr_tail exactly. Do NOT fabricate results.
Output the JSON you read from result.json, or the error details."""

_ANALYZE_TASK = """\
Execution failed. Details:

return_code: {return_code}

stderr (last 1500 chars):
{stderr_tail}

stdout (last 500 chars):
{stdout_tail}

Workspace root: {workspace_root}

Analyze the failure:
1. Call WorkspaceReadTool to read relevant source files if needed.
2. Identify the root cause.
3. Provide exactly 3–5 concrete fix_instructions as a JSON list.
4. Output a JSON object:
   {{
     "failure_diagnosis": "<root cause>",
     "fix_instructions": ["<fix 1>", "<fix 2>", ...],
     "repair_files": ["<file_path_1>", ...]
   }}"""

_EXEC_REPAIR_TASK = """\
You have real file-system tools. Use them now.

Workspace root:    {workspace_root}
Files to repair:   {repair_files}
Failure diagnosis: {diagnosis}
Fix instructions:
{fix_instructions}
User hint: {hint}

Stage 1 API definitions (authoritative — these are the ONLY valid signatures):
{stage1_api}

For each file in the repair list:
1. Call WorkspaceReadTool to read its current content.
2. Apply the fix instructions. When fixing TypeError on class instantiation,
   use ONLY the fields shown in Stage 1 API definitions above.
3. Call WorkspaceWriteTool to save the repaired content.
4. Call SyntaxCheckTool to verify the file compiles.
5. Fix any syntax errors before moving to the next file.
Output: DONE"""


# ── Agent builders ────────────────────────────────────────────────────────────

def _make_executor_agent(llm) -> Agent:
    return Agent(
        role="Experiment Executor",
        goal=(
            "Execute the experiment script and report exact results. "
            "Never fabricate metric values — report only what RunCommandTool returns."
        ),
        backstory=(
            "You run experiments and report exactly what happened. Every metric must come "
            "from an actual tool observation. If the run fails, you report the exact stderr."
        ),
        llm=llm,
        tools=[RunCommandTool(), ReadResultTool(), WorkspaceReadTool()],
        verbose=True,
        allow_delegation=False,
        max_iter=EXECUTOR_MAX_ITER,
    )


def _make_analyzer_agent(llm) -> Agent:
    return Agent(
        role="Result Analyzer",
        goal=(
            "Diagnose experiment failures and produce concrete, actionable fix instructions. "
            "Output structured JSON only."
        ),
        backstory=(
            "You are a data scientist specialising in debugging ML pipelines. You read error "
            "messages, identify root causes, and produce fix instructions precise enough for "
            "a coder to implement without clarification."
        ),
        llm=llm,
        tools=[WorkspaceReadTool(), ReadResultTool()],
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )


def _make_repair_agent(llm) -> Agent:
    from crew_tools import WorkspaceWriteTool, FileEditTool, SyntaxCheckTool
    return Agent(
        role="Execution Repair Engineer",
        goal="Fix the files that caused the experiment to fail.",
        backstory=(
            "You read the failure diagnosis and fix the broken files. "
            "You call tools immediately — no planning text first."
        ),
        llm=llm,
        tools=[WorkspaceReadTool(), WorkspaceWriteTool(), FileEditTool(), SyntaxCheckTool()],
        verbose=True,
        allow_delegation=False,
        max_iter=15,
    )


# ── Direct subprocess execution (faster than via agent) ──────────────────────

def _experiment_cmd(python_exe: str, entry_point: str, workspace_root: str) -> "list[str]":
    """실험 서브프로세스 실행 명령을 구성한다(스캐폴드 stable main.py CLI 규약).

    run_execution_phase가 재현성 기록의 entry_command에도 동일 명령을 쓰도록 공용화한다.
    """
    return [
        python_exe, entry_point,
        "--output-root", str(workspace_root),
        "--validation-tier", "full",
        "--dataset-origin", "real",
        "--evaluation-scope", "full_test",
        "--seed", "42",
        "--device", os.environ.get("MARS_EXPERIMENT_DEVICE", "cpu"),
    ]


def _run_script(
    entry_point: str,
    workspace_root: str,
    timeout: int,
    emit: Optional[Callable] = None,
    python_exe: Optional[str] = None,
) -> dict:
    """Run the experiment script with Popen + streaming stdout.

    stdout는 실시간으로 emit("exec_stdout", line) 이벤트를 발생시킨다.
    stderr는 완료 후 일괄 수집한다.
    """
    # 스캐폴드 stable main.py의 CLI 규약(scaffolds/builder.py build_parser)에 맞춰 인자 전달.
    # --output_root 미지정 시 기본값이 nested dir로 새어 phase3가 results/result.json을 못 찾고,
    # --validation_tier 기본값 "smoke"는 degenerate(1.0) 평가를 낳는다. 실제 평가를 위해 명시한다.
    # (scaffold cli는 parse_known_args라 비스캐폴드 entry에서도 안전하게 무시된다)
    cmd = _experiment_cmd(python_exe or sys.executable, entry_point, str(workspace_root))
    start = time.monotonic()
    stdout_lines: list[str] = []

    try:
        env = os.environ.copy()
        src_dir = str(Path(workspace_root) / "src")
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_path}" if existing_path else src_dir

        data_dir = DATA_CACHE_DIR or str(Path.home() / ".cache" / "mars_datasets")
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        env["DATA_DIR"] = data_dir

        proc = subprocess.Popen(
            cmd,
            cwd=workspace_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def _stream_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_lines.append(line)
                if emit is not None:
                    emit("exec_stdout", line.rstrip(), {"source": "stdout"})

        stream_thread = threading.Thread(target=_stream_stdout, daemon=True)
        stream_thread.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stream_thread.join(timeout=2)
            duration = time.monotonic() - start
            return {
                "return_code": -1,
                "stdout_tail": "".join(stdout_lines)[-2000:],
                "stderr_tail": f"Timeout after {timeout}s",
                "duration_s": duration,
            }

        stream_thread.join(timeout=5)
        assert proc.stderr is not None
        stderr_raw = proc.stderr.read()
        duration = time.monotonic() - start

        result: dict = {
            "return_code": proc.returncode,
            "stdout_tail": "".join(stdout_lines)[-2000:],
            "stderr_tail": stderr_raw[-2000:] if stderr_raw else "",
            "duration_s": duration,
        }
        # Try to read the result artifact. The scaffold's write_result_json may name the
        # file `result.json` OR `result_<run_id>.json` depending on the renderer, so prefer
        # the plain name and fall back to the newest `result*.json` in results/.
        results_dir = Path(workspace_root) / "results"
        result_path = results_dir / "result.json"
        if not result_path.exists() and results_dir.is_dir():
            candidates = sorted(
                results_dir.glob("result*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                result_path = candidates[0]
        if result_path.exists():
            try:
                result["result_json"] = json.loads(result_path.read_text(encoding="utf-8"))
                result["result_json_path"] = str(result_path)
            except Exception:
                result["result_json"] = {}
        return result

    except Exception as exc:
        return {
            "return_code": -2,
            "stdout_tail": "".join(stdout_lines)[-2000:],
            "stderr_tail": str(exc),
            "duration_s": time.monotonic() - start,
        }


# ── Contract verification (A3) ─────────────────────────────────────────────────
#
# S2 run에서 (1) 계획 success_criteria는 "3 epoch"였으나 실행은 1 epoch로 조용히
# 강등됐고 (근원: scaffold `build_parser`의 --epochs default=1 + _run_script가
# --epochs를 CLI로 전달하지 않음 → 실행규모 강등이 파이프라인 레벨에서 발생),
# (2) numeric metric이 없어도 execution_success=true로 통과했다.
# 아래 헬퍼들은 이런 계획/기대 대비 실제 결과의 불일치를 "감지·표면화"한다.
# 성공/실패 판정은 바꾸지 않는다 (정보 표면화가 목적).

# result.json에서 실제 epoch 수를 찾을 때 시도할 키 후보 (task 비의존, 방어적).
_EPOCH_KEYS = ("epochs", "epoch", "num_epochs", "n_epochs", "epochs_run", "max_epochs", "total_epochs")

# 일반적인 정량 metric 키 후보 (task 의존 — 존재하면 numeric contract를 만족한 것으로 본다).
_EXPECTED_METRIC_KEYS = (
    "accuracy", "acc", "top1", "top1_accuracy", "top5", "top5_accuracy",
    "rmse", "mae", "mse", "f1", "f1_score", "auc", "auroc", "bleu",
    "loss", "val_loss", "test_loss", "perplexity", "map", "precision", "recall",
)

# success_criteria 자유 텍스트에서 "3 epoch(s)" 형태를 뽑는 정규식.
_EPOCH_TEXT_RE = re.compile(r"(\d+)\s*(?:training\s*)?epochs?\b", re.IGNORECASE)


def _find_numeric(metrics: dict, keys) -> Optional[float]:
    """metrics(및 중첩 dict)에서 key 후보에 해당하는 numeric 값을 방어적으로 탐색."""
    def _coerce(v: Any) -> Optional[float]:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return None

    # 최상위 우선
    for k in keys:
        if k in metrics:
            c = _coerce(metrics[k])
            if c is not None:
                return c
    # 흔한 중첩 컨테이너 (metrics/summary/final 등) 안도 한 단계 탐색
    for container_key in ("metrics", "summary", "final", "final_metrics", "eval", "results"):
        sub = metrics.get(container_key)
        if isinstance(sub, dict):
            for k in keys:
                if k in sub:
                    c = _coerce(sub[k])
                    if c is not None:
                        return c
    return None


def _has_numeric_metric(metrics: dict) -> bool:
    """success/execution_success 등 비-metric 플래그를 제외하고 numeric metric이 있는지."""
    _skip = {"success", "execution_success", "iteration", "seed", "epochs", "batch_size",
             "num_workers", "epoch", "num_epochs", "n_epochs"}
    for k, v in metrics.items():
        if k in _skip:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        # 중첩 dict 안의 numeric도 인정
        if isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, (int, float)) and not isinstance(vv, bool):
                    return True
    return False


def _planned_epochs(plan: PlanBundle) -> Optional[int]:
    """planner/designer success_criteria 텍스트에서 계획된 epoch 수를 추출 (최댓값)."""
    texts: list[str] = []
    try:
        texts.extend(plan.planner.success_criteria or [])
    except Exception:
        pass
    try:
        texts.extend(plan.designer.success_criteria or [])
    except Exception:
        pass
    found: list[int] = []
    for t in texts:
        for m in _EPOCH_TEXT_RE.finditer(str(t)):
            try:
                found.append(int(m.group(1)))
            except ValueError:
                continue
    return max(found) if found else None


def check_contract(plan: PlanBundle, metrics: dict) -> dict:
    """실행 결과(metrics = result.json)를 계획/기대와 대조한 계약 검증 요약.

    반환 dict 구조:
      {
        "planned_epochs": Optional[int],
        "actual_epochs": Optional[float],
        "has_numeric_metric": bool,
        "expected_metric_found": bool,
        "violations": [ {"type": str, "expected": ..., "actual": ...}, ... ],
      }
    성공/실패를 결정하지 않는다 — 호출측이 이벤트로 표면화하는 용도.
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    planned_epochs = _planned_epochs(plan)
    actual_epochs = _find_numeric(metrics, _EPOCH_KEYS)
    has_numeric = _has_numeric_metric(metrics)
    expected_metric = _find_numeric(metrics, _EXPECTED_METRIC_KEYS)

    violations: list[dict] = []

    # (1) numeric metric 자체가 없음
    if not has_numeric:
        violations.append({
            "type": "CONTRACT_METRICS_MISSING",
            "expected": "at least one numeric metric in result.json",
            "actual": "none",
        })
    # (2) 실행규모(epoch) 강등: 계획 > 실제
    if planned_epochs is not None and actual_epochs is not None:
        if actual_epochs < planned_epochs:
            violations.append({
                "type": "EXECUTION_SCALE_DOWNGRADE",
                "expected": f"{planned_epochs} epochs (from success_criteria)",
                "actual": f"{actual_epochs:g} epochs (from result.json)",
            })

    return {
        "planned_epochs": planned_epochs,
        "actual_epochs": actual_epochs,
        "has_numeric_metric": has_numeric,
        "expected_metric_found": expected_metric is not None,
        "violations": violations,
    }


def _emit_contract_events(contract: dict, emit: EmitFn, attempt: int) -> None:
    """계약 검증 결과를 명시 이벤트로 표면화. 정상(위반 없음)이면 EXECUTION_SCALE만 정보성 emit."""
    planned = contract.get("planned_epochs")
    actual = contract.get("actual_epochs")

    # 실행 규모는 항상 정보성으로 남긴다 (계획값과 함께).
    emit(
        "EXECUTION_SCALE",
        f"[Phase 3] Execution scale — planned_epochs={planned}, actual_epochs={actual}",
        {
            "planned_epochs": planned,
            "actual_epochs": actual,
            "attempt": attempt,
        },
    )

    for v in contract.get("violations", []):
        vtype = v.get("type", "CONTRACT_VIOLATION")
        if vtype == "CONTRACT_METRICS_MISSING":
            emit(
                "CONTRACT_METRICS_MISSING",
                "[Phase 3] Contract: result.json has no numeric metrics "
                f"(expected: {v.get('expected')}).",
                {"attempt": attempt, **v},
            )
        else:
            emit(
                "CONTRACT_VIOLATION",
                f"[Phase 3] Contract violation ({vtype}): "
                f"expected {v.get('expected')} but got {v.get('actual')}.",
                {"attempt": attempt, **v},
            )


# ── Phase 3 main function ─────────────────────────────────────────────────────

def run_execution_phase(
    plan: PlanBundle,
    coding_result: CodingResult,
    guidance_registry: GuidanceRegistry,
    emit: EmitFn,
    llm=None,
    cancel: Optional[CancellationToken] = None,
    python_exe: Optional[str] = None,
) -> ExecutorResult:
    """Run the experiment and collect results. Escalates to user on persistent failure.

    Returns:
        ExecutorResult with success flag, metrics, and artifact paths.
    """
    analyzer_llm = create_llm_for_agent("result_analyzer")
    repair_llm = create_llm_for_agent("code_generator")

    workspace_root = plan.workspace.workspace_dir
    run_id = plan.workspace.run_id
    entry_point = plan.designer.entry_point or "src/main.py"
    attempt = 0
    hint = ""

    # Stage 1 API surface — repair agent가 올바른 클래스 정의를 참조하도록 미리 빌드
    from phases.phase2_coding import _build_dep_context
    stage1_paths = [
        fr.path
        for s in coding_result.stages
        if s.stage == 1
        for fr in s.files
        if fr.written
    ]
    stage1_api = _build_dep_context(stage1_paths, workspace_root) if stage1_paths else "(none)"
    diagnosis = ""
    fix_instructions: list[str] = []

    # ── 재현성 메타데이터(P1-3): 실험을 실행할 python 환경을 기록·표면화한다.
    # MARS의 재현성은 1차 지표이므로 실행 전에 env/버전/패키지 지문을 남긴다.
    resolved_python = python_exe or sys.executable
    if python_exe and not Path(python_exe).is_file():
        emit(
            "AGENT_MESSAGE",
            f"[Phase 3] 지정된 실행 환경을 찾을 수 없어 현재 인터프리터로 대체합니다: {python_exe}",
            {"requested_python": python_exe},
        )
        resolved_python = sys.executable
    repro_env: dict = {}
    try:
        from core.env_detect import describe_python, requirements_hash
        env_desc = describe_python(resolved_python)
        device = os.environ.get("MARS_EXPERIMENT_DEVICE", "cpu")
        repro_env = {
            **env_desc,
            "device": device,
            "seed": 42,
            "entry_command": " ".join(
                _experiment_cmd(resolved_python, entry_point, str(workspace_root))
            ),
            "requirements_hash": requirements_hash(env_desc.get("packages", {})),
        }
        emit(
            "EXECUTION_ENVIRONMENT",
            f"[Phase 3] 실행 환경: {repro_env.get('env_name', '?')} · "
            f"Python {repro_env.get('python_version', '?')} · device {device} · "
            f"{len(env_desc.get('packages', {}))} pkgs (fp {repro_env.get('requirements_hash') or 'n/a'})",
            repro_env,
        )
    except Exception:
        logging.getLogger(__name__).exception("Failed to capture reproducibility metadata")

    while True:
        if cancel and cancel.is_cancelled:
            return ExecutorResult(success=False, stderr_tail="Cancelled")

        attempt += 1
        emit(
            "AGENT_MESSAGE",
            f"[Phase 3] Running experiment (attempt {attempt}): python {entry_point}",
            {"attempt": attempt, "entry_point": entry_point},
        )

        run_result = _run_script(
            entry_point, workspace_root, EXPERIMENT_TIMEOUT_SECS,
            emit=emit, python_exe=resolved_python,
        )

        if run_result["return_code"] == 0:
            rj = run_result.get("result_json", {})
            metrics = rj if isinstance(rj, dict) else {}

            # L2: result.json 성공 플래그가 False면 rc=0이어도 실패로 처리
            # (스크립트가 graceful shutdown 후 rc=0 종료해도 실험 실패는 실패)
            # 스크립트마다 플래그 키 이름이 다름(success / execution_success) → 둘 다 검사
            success_flag = metrics.get("success", metrics.get("execution_success", True))
            if not success_flag:
                error_msg = str(metrics.get("error", "result.json success flag=False"))[:400]
                emit(
                    "AGENT_MESSAGE",
                    f"[Phase 3] rc=0 but result.json.success=False — treating as failure: {error_msg}",
                    {"false_success": True, "error": error_msg, "attempt": attempt},
                )
                run_result = {**run_result, "return_code": -3, "stderr_tail": error_msg}
            else:
                # L3 / A3: 계약 검증 — 실행 결과를 계획·기대와 대조해 불일치를 표면화.
                # (실패로 강제 전환하지 않음. 이벤트 emit + contract_check 메타 첨부만.)
                contract = check_contract(plan, metrics)
                _emit_contract_events(contract, emit, attempt)

                # contract_check 요약을 metrics(=반환 metrics)에 첨부해 Phase 4/게이트가
                # 후속 판정에 활용할 수 있게 한다. 원본 result.json 파일은 건드리지 않는다.
                metrics_out = {**metrics, "contract_check": contract}

                artifact_paths = _collect_artifacts(workspace_root)
                emit(
                    "AGENT_MESSAGE",
                    f"[Phase 3] Experiment succeeded. Metrics: {_fmt_metrics(metrics)}",
                    {"success": True, "metrics": metrics, "attempt": attempt,
                     "contract_violations": [v["type"] for v in contract["violations"]]},
                )
                return ExecutorResult(
                    success=True,
                    return_code=0,
                    metrics=metrics_out,
                    artifact_paths=artifact_paths,
                    stdout_tail=run_result["stdout_tail"],
                    stderr_tail=run_result["stderr_tail"],
                    result_json_path=run_result.get("result_json_path", ""),
                    environment=repro_env,
                )

        # ── Failure path (rc != 0 또는 L2 실패) ─────────────────────────────
        stderr = run_result["stderr_tail"]
        emit(
            "AGENT_MESSAGE",
            f"[Phase 3] Experiment failed (rc={run_result['return_code']}). "
            f"Analyzing...",
            {"attempt": attempt, "rc": run_result["return_code"], "stderr_tail": stderr[-300:]},
        )

        # Analyze
        analyze_task = Task(
            description=_ANALYZE_TASK.format(
                return_code=run_result["return_code"],
                stderr_tail=run_result.get("stderr_tail", "")[-1500:],
                stdout_tail=run_result.get("stdout_tail", "")[-500:],
                workspace_root=workspace_root,
            ),
            expected_output="JSON with failure_diagnosis, fix_instructions, repair_files.",
            agent=_make_analyzer_agent(analyzer_llm),
        )
        analyzer_output = Crew(
            agents=[analyze_task.agent], tasks=[analyze_task], verbose=False
        ).kickoff()
        analyzer_raw = getattr(analyzer_output, "raw", "") or str(analyzer_output)
        analysis = _parse_analysis(analyzer_raw)
        diagnosis = analysis.get("failure_diagnosis", stderr[:300])
        fix_instructions = analysis.get("fix_instructions", [])
        repair_files = analysis.get("repair_files", [])

        emit(
            "AGENT_MESSAGE",
            f"[Phase 3] Diagnosis: {diagnosis[:200]}",
            {"diagnosis": diagnosis, "repair_files": repair_files},
        )

        if attempt >= MAX_EXEC_REPAIR_ATTEMPTS or not repair_files:
            # Escalate — either max attempts exhausted or nothing to repair (env/network issue)
            reason = (
                f"after {attempt} attempts"
                if attempt >= MAX_EXEC_REPAIR_ATTEMPTS
                else "no fixable files identified (likely environment/network issue)"
            )
            from orchestration.approval_registry import GuidanceGate
            gate = GuidanceGate(
                file_path=entry_point,
                error_msg=stderr,
                attempt_count=attempt,
            )
            guidance_registry.register(run_id, entry_point, gate)
            emit(
                "USER_GUIDANCE_NEEDED",
                f"[Phase 3] Cannot fix experiment ({reason}). "
                f"Waiting for your guidance.",
                {
                    "run_id": run_id,
                    "entry": entry_point,
                    "diagnosis": diagnosis,
                    "error": stderr[-500:],
                    "attempts": attempt,
                    "options": ["continue", "skip"],
                },
            )
            resolved = gate.wait(timeout=USER_GUIDANCE_TIMEOUT_SECS)
            guidance_registry.remove(run_id, entry_point)

            if not resolved or gate.should_skip:
                emit(
                    "AGENT_MESSAGE",
                    "[Phase 3] Execution skipped by user or timeout — recording partial results.",
                    {"skipped": True},
                )
                return ExecutorResult(
                    success=False,
                    return_code=run_result["return_code"],
                    stderr_tail=stderr,
                )

            hint = gate.hint or ""
            attempt = 0
            continue

        # Repair files
        if repair_files:
            fi_text = "\n".join(f"  - {fi}" for fi in fix_instructions)
            repair_task = Task(
                description=_EXEC_REPAIR_TASK.format(
                    workspace_root=workspace_root,
                    repair_files=", ".join(repair_files),
                    diagnosis=diagnosis,
                    fix_instructions=fi_text,
                    hint=hint or "(none)",
                    stage1_api=stage1_api,
                ),
                expected_output="DONE",
                agent=_make_repair_agent(repair_llm),
            )
            Crew(agents=[repair_task.agent], tasks=[repair_task], verbose=False).kickoff()
            hint = ""


def _parse_analysis(raw: str) -> dict:
    data = extract_json(raw)
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        return data
    return {"failure_diagnosis": raw[:300], "fix_instructions": [], "repair_files": []}


def _collect_artifacts(workspace_root: str) -> list[str]:
    """Collect paths of result files produced by the experiment."""
    results_dir = Path(workspace_root) / "results"
    if not results_dir.exists():
        return []
    return [str(p) for p in results_dir.iterdir() if p.is_file()]


def _fmt_metrics(metrics: dict) -> str:
    if not metrics:
        return "(no metrics)"
    parts = []
    for k, v in list(metrics.items())[:5]:
        parts.append(f"{k}={v}")
    return ", ".join(parts)
