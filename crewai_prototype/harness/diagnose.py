"""
harness/diagnose.py
===================
Runs a structured pass/fail checklist on a completed V3 pipeline run.

Usage:
    python harness/diagnose.py                  # latest run
    python harness/diagnose.py v3_ee82e6e31429  # specific run_id
    python harness/diagnose.py --all            # all runs, summary table
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

OUTPUTS_ROOT = Path(__file__).parent.parent / "outputs"
PYTHON = sys.executable

# Force UTF-8 output on Windows so Unicode chars don't crash cp949
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── ANSI colours ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg: str) -> str:   return f"{GREEN}✓ PASS{RESET}  {msg}"
def fail(msg: str) -> str: return f"{RED}✗ FAIL{RESET}  {msg}"
def warn(msg: str) -> str: return f"{YELLOW}⚠ WARN{RESET}  {msg}"
def info(msg: str) -> str: return f"{BLUE}ℹ INFO{RESET}  {msg}"


# ── Data model ───────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str = ""
    suggestion: str = ""

    def fmt(self) -> str:
        line = ok(self.label) if self.passed else fail(self.label)
        if self.detail:
            line += f"\n         {self.detail}"
        if not self.passed and self.suggestion:
            line += f"\n         {YELLOW}→ {self.suggestion}{RESET}"
        return line


@dataclass
class PhaseReport:
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _file_contains(path: Path, pattern: str) -> bool:
    try:
        return pattern in path.read_text(encoding="utf-8")
    except Exception:
        return False


def _py_compile_ok(path: Path, ws: Path) -> tuple[bool, str]:
    """Return (ok, stderr) for a py_compile check."""
    rel = path.relative_to(ws)
    result = subprocess.run(
        [PYTHON, "-m", "py_compile", str(rel)],
        cwd=str(ws),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0, result.stderr.strip()


def _func_in_file(path: Path, func_name: str) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    return True
    except Exception:
        pass
    return False


def _is_stub(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
        return "FileCoder failed to generate" in text or "stub_error" in text
    except Exception:
        return False


def _latest_run_dir() -> Optional[Path]:
    dirs = sorted(
        [d for d in OUTPUTS_ROOT.iterdir() if d.is_dir() and d.name.startswith("v3_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _exec_logs(ws: Path) -> list[Path]:
    log_dir = ws / "logs"
    if not log_dir.exists():
        return []
    return sorted(log_dir.glob("exec_*.log"), key=lambda p: p.stat().st_mtime)


def _parse_exec_log(log_path: Path) -> dict:
    """Extract RC, duration, stdout, stderr from an exec log."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    rc_match = re.search(r"RC:\s*(\d+)", text)
    dur_match = re.search(r"DURATION:\s*([\d.]+)s", text)
    return {
        "rc": int(rc_match.group(1)) if rc_match else -1,
        "duration_s": float(dur_match.group(1)) if dur_match else 0.0,
        "stdout": re.search(r"STDOUT:\n(.*?)(?:STDERR:|$)", text, re.DOTALL),
        "stderr_snippet": text[-800:] if "Error" in text else "",
    }


def _accuracy_in_result(result: dict) -> Optional[float]:
    """Recursively scan for accuracy values, including nested results lists."""
    acc_keys = ("top1_accuracy", "accuracy", "top_1_accuracy", "val_accuracy", "eval_accuracy")

    def _scan(obj: any, depth: int = 0) -> Optional[float]:
        if depth > 6:
            return None
        if isinstance(obj, dict):
            for k in acc_keys:
                v = obj.get(k)
                if v is not None:
                    try:
                        f = float(v)
                        if f > 0.0:  # skip 0.0 (failed trials)
                            return f
                    except Exception:
                        pass
            for v in obj.values():
                found = _scan(v, depth + 1)
                if found is not None:
                    return found
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                found = _scan(item, depth + 1)
                if found is not None:
                    return found
        return None

    return _scan(result)


# ── Phase checkers ───────────────────────────────────────────────────────────
def check_phase1(ws: Path) -> PhaseReport:
    p = PhaseReport("Phase 1 — Planner / Designer")
    handoff = ws / "handoff"

    # planner_result.json
    pr = handoff / "planner_result.json"
    p.checks.append(CheckResult(
        "planner_result.json exists",
        pr.exists(),
        suggestion="PlannerResult validation failed — check coordinator log for 'validation failed' events",
    ))

    # designer_result.json
    dr = handoff / "designer_result.json"
    p.checks.append(CheckResult(
        "designer_result.json exists",
        dr.exists(),
        suggestion="DesignerResult validation failed — handoff_models.py coercion may not have covered the LLM's output format",
    ))

    # coder_context.json
    cc = handoff / "coder_context.json"
    cc_data = _load_json(cc) or {}
    p.checks.append(CheckResult(
        "coder_context.json written",
        cc.exists(),
        suggestion="ScaffoldService or _write_coder_context_file crashed before writing",
    ))
    if cc.exists():
        impl_in_order = "src/experiment_impl.py" in cc_data.get("generation_order", [])
        p.checks.append(CheckResult(
            "experiment_impl.py in generation_order",
            impl_in_order,
            detail=f"generation_order = {cc_data.get('generation_order', [])}",
            suggestion="gen_order logic in coordinator may have excluded it again",
        ))
        stack = cc_data.get("stack_rule", "")
        p.checks.append(CheckResult(
            f"stack_rule set ('{stack[:60]}')",
            bool(stack),
            suggestion="scaffold_type not detected → _STACK_RULES lookup failed",
        ))

    return p


def check_phase1d(ws: Path) -> PhaseReport:
    p = PhaseReport("Phase 1d — FileCoder (code generation)")
    manifest_data = _load_json(ws / "project_manifest.json") or {}
    mutable = manifest_data.get("mutable_files", [
        "src/experiment_impl.py", "src/data.py", "src/models.py",
        "src/train.py", "src/evaluate.py", "src/utils.py", "src/metrics.py",
    ])

    written = [f for f in mutable if (ws / f).exists()]
    missing = [f for f in mutable if not (ws / f).exists()]

    p.checks.append(CheckResult(
        f"Files written: {len(written)}/{len(mutable)}",
        len(missing) == 0,
        detail=f"missing: {missing}" if missing else "",
        suggestion="FileCoder exited before writing some files. Check max_iter or py_compile errors in run log.",
    ))

    # experiment_impl.py deep check
    impl = ws / "src" / "experiment_impl.py"
    impl_exists = impl.exists()
    impl_stub = _is_stub(impl) if impl_exists else False

    p.checks.append(CheckResult(
        "experiment_impl.py exists",
        impl_exists,
        suggestion="All 3 FileCoder attempts (including repair) failed to write the file",
    ))
    if impl_exists:
        p.checks.append(CheckResult(
            "experiment_impl.py is NOT a stub",
            not impl_stub,
            detail="File contains 'FileCoder failed' — coordinator fallback stub was used" if impl_stub else "",
            suggestion="FileCoder never called WorkspaceWriteTool for this file. Check if py_compile errors in other files consumed all iterations.",
        ))
        p.checks.append(CheckResult(
            "has run_single_experiment()",
            _func_in_file(impl, "run_single_experiment"),
            suggestion="FileCoder wrote the file but forgot the required interface function",
        ))
        p.checks.append(CheckResult(
            "has run_selected_experiments()",
            _func_in_file(impl, "run_selected_experiments"),
            suggestion="Same as above — check coder_context.json symbols list",
        ))
        ok_compile, err = _py_compile_ok(impl, ws)
        p.checks.append(CheckResult(
            "experiment_impl.py compiles (py_compile)",
            ok_compile,
            detail=err[:200] if err else "",
            suggestion="Syntax error in generated code — repair crew should have caught this",
        ))

    # Key dependency files — use actual mutable_files from coder_context, not hardcoded names
    cc_data = _load_json(ws / "handoff" / "coder_context.json") or {}
    mutable_from_ctx = cc_data.get("mutable_files", [])
    key_deps = [f for f in mutable_from_ctx if f != "src/experiment_impl.py"] or [
        "src/data.py", "src/models.py", "src/train.py", "src/evaluate.py"
    ]
    dep_written = [d for d in key_deps if (ws / d).exists() and not _is_stub(ws / d)]
    dep_missing = [d for d in key_deps if not (ws / d).exists() or _is_stub(ws / d)]
    p.checks.append(CheckResult(
        f"Dependency files written: {len(dep_written)}/{len(key_deps)}",
        len(dep_missing) == 0,
        detail=f"missing/stub: {dep_missing}" if dep_missing else "",
        suggestion="FileCoder ran out of iterations before writing these files. Check max_iter setting.",
    ))

    return p


def check_phase2(ws: Path) -> PhaseReport:
    p = PhaseReport("Phase 2 — Execution & Analysis")
    logs = _exec_logs(ws)

    p.checks.append(CheckResult(
        f"Execution attempted ({len(logs)} log(s))",
        len(logs) > 0,
        suggestion="Phase 2 never ran — experiment_impl.py gate may have killed the pipeline",
    ))

    if not logs:
        return p

    last_log = logs[-1]
    parsed = _parse_exec_log(last_log)
    rc = parsed["rc"]
    dur = parsed["duration_s"]

    p.checks.append(CheckResult(
        f"Last exec RC=0 (actual={rc})",
        rc == 0,
        detail=parsed["stderr_snippet"][:300] if parsed["stderr_snippet"] else "",
        suggestion="Python exception during experiment. Check logs/ for stderr. Common: import error, CUDA OOM, bad experiment_impl logic.",
    ))
    p.checks.append(CheckResult(
        f"Execution duration > 5s (actual={dur}s)",
        dur > 5.0,
        detail="Very short duration usually means stub or import-only run" if dur <= 5.0 else "",
        suggestion="Stub experiment_impl ran (0.1–0.3s) or model never started training. Check experiment_impl.py content.",
    ))

    result_path = ws / "results" / "result.json"
    result_data = _load_json(result_path) or {}
    p.checks.append(CheckResult(
        "results/result.json present",
        result_path.exists(),
        suggestion="write_result_json() in artifacts.py never called — experiment_impl crashed before finishing",
    ))

    if result_path.exists():
        exec_ok = bool(result_data.get("execution_success"))
        p.checks.append(CheckResult(
            "result.json: execution_success=true",
            exec_ok,
            detail=result_data.get("error", "")[:200],
            suggestion="Experiment returned failure status. Check 'error' key and exec logs for traceback.",
        ))

        stub_err = result_data.get("status") == "stub_error"
        p.checks.append(CheckResult(
            "result.json: NOT stub_error",
            not stub_err,
            suggestion="Stub was used for execution. FileCoder must write a real experiment_impl.py.",
        ))

        acc = _accuracy_in_result(result_data)
        p.checks.append(CheckResult(
            f"Accuracy metric present (value={acc})",
            acc is not None and acc > 0.01,
            detail=f"Keys in result: {list(result_data.keys())}",
            suggestion="experiment_impl.py completed but didn't return an accuracy key. Check what keys it writes to result dict.",
        ))

    return p


def check_phase3(ws: Path, run_dir: Path, topic: str = "") -> PhaseReport:
    p = PhaseReport("Phase 3 — Writer / Report")

    report = run_dir / "report.md"
    p.checks.append(CheckResult(
        "report.md exists",
        report.exists(),
        suggestion="Writer agent failed to call WriteReportTool, or WriteReportTool wrote to wrong path. Check report_path in coordinator.",
    ))

    if report.exists():
        text = report.read_text(encoding="utf-8", errors="replace")
        has_numbers = bool(re.search(r"\d+\.\d+", text))
        p.checks.append(CheckResult(
            "Report contains numeric values (accuracy/loss)",
            has_numbers,
            suggestion="Writer hallucinated a report without real numbers. result_summary input may not have suppressed it.",
        ))

        wrong_topics = ["Breast Cancer", "breast cancer", "iris", "MNIST", "titanic"]
        hallucinated = any(w in text for w in wrong_topics)
        p.checks.append(CheckResult(
            "Report topic matches experiment (no hallucination)",
            not hallucinated,
            detail=next((w for w in wrong_topics if w in text), ""),
            suggestion="Writer used training-data knowledge instead of actual results. Add stronger 'do not invent' constraint.",
        ))

        if topic:
            kw = topic.lower().replace(" ", "")
            topic_hit = any(w in text.lower() for w in ["resnet", "vit", "cifar", "vision"])
            p.checks.append(CheckResult(
                "Report mentions expected keywords (ResNet/ViT/CIFAR)",
                topic_hit,
                suggestion="Writer ignored coder_context.json topic — check Step 2 WorkspaceReadTool call in writer task",
            ))

    return p


def check_overall(ws: Path) -> PhaseReport:
    p = PhaseReport("Overall")
    tel_path = ws / "logs" / "telemetry_summary.json"
    if tel_path.exists():
        tel = _load_json(tel_path) or {}
        repair = tel.get("repair_count", 0)
        p.checks.append(CheckResult(
            f"Repair count ≤ 1 (actual={repair})",
            isinstance(repair, int) and repair <= 1,
            suggestion="Multiple repairs needed — experiment_impl.py quality is low or dependencies are broken",
        ))
    else:
        # No telemetry written — backend may have restarted during run; skip repair check
        p.checks.append(CheckResult(
            "Telemetry / repair count (telemetry_summary.json missing — backend restarted?)",
            True,
            suggestion="",
        ))
    return p


# ── Main diagnostic ──────────────────────────────────────────────────────────
def diagnose(run_id: Optional[str] = None) -> dict:
    if run_id:
        run_dir = OUTPUTS_ROOT / run_id
    else:
        run_dir = _latest_run_dir()

    if run_dir is None or not run_dir.exists():
        print(f"{RED}No run directory found.{RESET}")
        sys.exit(1)

    ws = run_dir / "workspace"
    cc_data = _load_json(ws / "handoff" / "coder_context.json") or {}
    topic = cc_data.get("topic", "")

    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  DIAGNOSTIC — {run_dir.name}{RESET}")
    if topic:
        print(f"  Topic: {topic}")
    print(f"{BOLD}{'═'*60}{RESET}\n")

    phases = [
        check_phase1(ws),
        check_phase1d(ws),
        check_phase2(ws),
        check_phase3(ws, run_dir, topic),
        check_overall(ws),
    ]

    total_pass = total_fail = 0
    summary: dict[str, tuple[int, int]] = {}

    for phase in phases:
        print(f"{BOLD}{phase.name}{RESET}")
        print(f"{'─'*50}")
        for c in phase.checks:
            print(f"  {c.fmt()}")
        print()
        total_pass += phase.n_pass
        total_fail += phase.n_fail
        summary[phase.name] = (phase.n_pass, phase.n_fail)

    # Summary bar
    print(f"{BOLD}{'═'*60}{RESET}")
    overall_ok = total_fail == 0
    status_str = f"{GREEN}ALL PASS{RESET}" if overall_ok else f"{RED}{total_fail} FAIL(S){RESET}"
    print(f"  Result: {total_pass} passed, {total_fail} failed  →  {status_str}")
    print(f"{BOLD}{'═'*60}{RESET}\n")

    return {
        "run_id": run_dir.name,
        "topic": topic,
        "passed": overall_ok,
        "total_pass": total_pass,
        "total_fail": total_fail,
        "phases": {k: {"pass": v[0], "fail": v[1]} for k, v in summary.items()},
    }


def diagnose_all() -> None:
    dirs = sorted(
        [d for d in OUTPUTS_ROOT.iterdir() if d.is_dir() and d.name.startswith("v3_")],
        key=lambda d: d.stat().st_mtime,
    )
    if not dirs:
        print("No runs found.")
        return

    header = f"{'RUN_ID':<22}  {'TOPIC':<35}  P1  P1d  P2  P3  TOTAL"
    print(f"\n{BOLD}{header}{RESET}")
    print("─" * len(header))

    for d in dirs[-10:]:  # last 10 runs
        ws = d / "workspace"
        cc = _load_json(ws / "handoff" / "coder_context.json") or {}
        topic = cc.get("topic", "")[:33]
        phases = [
            check_phase1(ws),
            check_phase1d(ws),
            check_phase2(ws),
            check_phase3(ws, d, cc.get("topic", "")),
        ]
        cols = [f"{p.n_pass}/{len(p.checks)}" for p in phases]
        total_fail = sum(p.n_fail for p in phases)
        color = GREEN if total_fail == 0 else RED
        print(f"{d.name:<22}  {topic:<35}  {'  '.join(cols)}  {color}{'OK' if total_fail == 0 else str(total_fail)+' fail'}{RESET}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose a V3 pipeline run")
    parser.add_argument("run_id", nargs="?", help="Run ID (e.g. v3_abc123). Omit for latest.")
    parser.add_argument("--all", action="store_true", help="Show summary table for all recent runs")
    args = parser.parse_args()

    if args.all:
        diagnose_all()
    else:
        result = diagnose(args.run_id)
        sys.exit(0 if result["passed"] else 1)
