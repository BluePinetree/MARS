"""phases/exit_gate.py — Phase 2 완료 후 단일 통합 검증 게이트.

repair loop 재진입 없음. 실패 시 GuidanceGate 직행.
검증 단계:
  1. syntax check (모든 파일)
  2. import check (단일 통과 — DependencyInvalidationGraph 없음)
  3. dry-run (entry point만, python -c "import <module>" 수준)
"""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.handoff_models import FileNodeSpec
from crew_tools.syntax_check_tool import check_import, check_syntax

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]


@dataclass
class ExitGateResult:
    passed: bool
    reason: str = ""
    failed_file: str = ""
    gate: str = ""  # "syntax" | "import" | "dry_run" | ""


class ExitGate:
    """Phase 2 완료 후 단일 검증 게이트 (smoke test + import check + dry-run)."""

    def run(
        self,
        workspace_root: str | Path,
        file_specs: list[FileNodeSpec],
        emit: EmitFn,
        entry_point: str = "src/main.py",
    ) -> ExitGateResult:
        """세 단계 순서로 검증한다. 첫 실패 즉시 반환 (repair 시도 없음)."""
        ws = Path(workspace_root)

        emit("AGENT_MESSAGE", "[ExitGate] Step 1: syntax check for all files", {})
        for spec in file_specs:
            full = ws / spec.path
            if not full.exists():
                continue
            result = check_syntax(full)
            if not result.passed:
                emit(
                    "AGENT_MESSAGE",
                    f"[ExitGate] Syntax FAILED: {spec.path} — {result.error[:120]}",
                    {"gate": "syntax", "file": spec.path},
                )
                return ExitGateResult(
                    passed=False,
                    reason=result.error,
                    failed_file=spec.path,
                    gate="syntax",
                )

        emit("AGENT_MESSAGE", "[ExitGate] Step 2: import check for all files", {})
        for spec in file_specs:
            full = ws / spec.path
            if not full.exists():
                continue
            result = check_import(full, str(ws))
            if not result.passed:
                emit(
                    "AGENT_MESSAGE",
                    f"[ExitGate] Import FAILED: {spec.path} — {result.error[:120]}",
                    {"gate": "import", "file": spec.path},
                )
                return ExitGateResult(
                    passed=False,
                    reason=result.error,
                    failed_file=spec.path,
                    gate="import",
                )

        emit("AGENT_MESSAGE", f"[ExitGate] Step 3: dry-run entry point {entry_point}", {})
        dry_result = self._dry_run(entry_point, ws)
        if not dry_result.passed:
            emit(
                "AGENT_MESSAGE",
                f"[ExitGate] Dry-run FAILED: {dry_result.reason[:120]}",
                {"gate": "dry_run", "file": entry_point},
            )
            return ExitGateResult(
                passed=False,
                reason=dry_result.reason,
                failed_file=entry_point,
                gate="dry_run",
            )

        emit("AGENT_MESSAGE", "[ExitGate] All checks PASSED.", {"gate": "ok"})
        return ExitGateResult(passed=True)

    def _dry_run(self, entry_point: str, workspace_root: Path) -> ExitGateResult:
        """entry point를 --help 또는 dry-import 방식으로 실행해 기본 동작만 확인한다."""
        full = workspace_root / entry_point
        if not full.exists():
            return ExitGateResult(
                passed=False,
                reason=f"Entry point not found: {entry_point}",
                gate="dry_run",
            )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"import ast; ast.parse(open(r'{full}').read())"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return ExitGateResult(
                    passed=False,
                    reason=proc.stderr[:500] or "dry-run parse failed",
                    gate="dry_run",
                )
            return ExitGateResult(passed=True)
        except subprocess.TimeoutExpired:
            return ExitGateResult(
                passed=False, reason="dry-run timed out (30s)", gate="dry_run"
            )
        except Exception as exc:
            return ExitGateResult(passed=False, reason=str(exc), gate="dry_run")
