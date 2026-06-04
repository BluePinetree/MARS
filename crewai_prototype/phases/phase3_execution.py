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
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

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

For each file in the repair list:
1. Call WorkspaceReadTool to read its current content.
2. Apply the fix instructions.
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

def _run_script(
    entry_point: str,
    workspace_root: str,
    timeout: int,
    emit: Optional[Callable] = None,
) -> dict:
    """Run the experiment script with Popen + streaming stdout.

    stdout는 실시간으로 emit("exec_stdout", line) 이벤트를 발생시킨다.
    stderr는 완료 후 일괄 수집한다.
    """
    cmd = [sys.executable, entry_point]
    start = time.monotonic()
    stdout_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
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
        # Try to read result.json
        result_path = Path(workspace_root) / "results" / "result.json"
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


# ── Phase 3 main function ─────────────────────────────────────────────────────

def run_execution_phase(
    plan: PlanBundle,
    coding_result: CodingResult,
    guidance_registry: GuidanceRegistry,
    emit: EmitFn,
    llm=None,
    cancel: Optional[CancellationToken] = None,
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
    diagnosis = ""
    fix_instructions: list[str] = []

    while True:
        if cancel and cancel.is_cancelled:
            return ExecutorResult(success=False, stderr_tail="Cancelled")

        attempt += 1
        emit(
            "AGENT_MESSAGE",
            f"[Phase 3] Running experiment (attempt {attempt}): python {entry_point}",
            {"attempt": attempt, "entry_point": entry_point},
        )

        run_result = _run_script(entry_point, workspace_root, EXPERIMENT_TIMEOUT_SECS, emit=emit)

        if run_result["return_code"] == 0:
            rj = run_result.get("result_json", {})
            metrics = rj if isinstance(rj, dict) else {}
            artifact_paths = _collect_artifacts(workspace_root)

            if not metrics.get("success", True):
                emit(
                    "AGENT_MESSAGE",
                    f"[Phase 3] Warning: experiment exited cleanly (rc=0) but "
                    f"result.json reports success=false. "
                    f"Error: {str(metrics.get('error', ''))[:200]}. "
                    f"Proceeding to paper writing with partial results.",
                    {"warning": "exec_success_false", "error": metrics.get("error", "")},
                )

            emit(
                "AGENT_MESSAGE",
                f"[Phase 3] Experiment succeeded. Metrics: {_fmt_metrics(metrics)}",
                {"success": True, "metrics": metrics, "attempt": attempt},
            )
            return ExecutorResult(
                success=True,
                return_code=0,
                metrics=metrics,
                artifact_paths=artifact_paths,
                stdout_tail=run_result["stdout_tail"],
                stderr_tail=run_result["stderr_tail"],
                result_json_path=run_result.get("result_json_path", ""),
            )

        # ── Failure path ──────────────────────────────────────────────────────
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

        if attempt >= MAX_EXEC_REPAIR_ATTEMPTS:
            # Escalate
            from orchestration.approval_registry import GuidanceGate
            gate = GuidanceGate(
                file_path=entry_point,
                error_msg=stderr,
                attempt_count=attempt,
            )
            guidance_registry.register(run_id, entry_point, gate)
            emit(
                "USER_GUIDANCE_NEEDED",
                f"[Phase 3] Cannot fix experiment after {attempt} attempts. "
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
