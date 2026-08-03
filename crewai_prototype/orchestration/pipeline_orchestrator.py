"""orchestration/pipeline_orchestrator.py — V4 Pipeline Orchestrator.

Coordinates all five phases on a background thread per run:
  Phase 0: Workspace setup
  Phase 1: Planner + Designer + User approval gate
  Phase 2: Staged coding with escalation loop
  Phase 3: Experiment execution with escalation loop
  Phase 4: Section-by-section paper writing

The API layer interacts with running pipelines through:
  ApprovalRegistry  — POST /runs/{id}/approve
  GuidanceRegistry  — POST /runs/{id}/guidance
  CancellationRegistry — DELETE /runs/{id}
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from runtime.models import RunSession
from orchestration.checkpoint_manager import CheckpointManager
from orchestration.context_injection_queue import ContextInjectionQueue
from orchestration.extension_proposer import ExtensionProposer
from orchestration.failure_pattern_detector import FailurePatternDetector
from orchestration.preflight_clarifier import PreflightClarifier
from orchestration.approval_registry import (
    ApprovalRegistry,
    CancellationRegistry,
    CancellationToken,
    GuidanceRegistry,
)
from phases.phase0_workspace import setup_workspace
from phases.phase1_planning import run_planning_phase
from phases.phase2_coding import run_coding_phase
from phases.phase3_execution import run_execution_phase
from phases.phase4_writing import run_writing_phase
from runtime.event_store import EventStore
from runtime.models import RunEvent, normalize_event_type
from runtime.session_store import SessionStore

logger = logging.getLogger(__name__)


# ── Prepared run ──────────────────────────────────────────────────────────────

@dataclass
class PreparedRun:
    run_id: str
    session_id: str
    research_topic: str
    goal: str
    user_workspace_path: Optional[str]
    session: Any  # RunSession


# ── Orchestrator ──────────────────────────────────────────────────────────────

class PipelineOrchestrator:
    """Manages the lifecycle of V4 research pipeline runs."""

    def __init__(
        self,
        session_store: SessionStore,
        event_store: EventStore,
        approval_registry: ApprovalRegistry,
        guidance_registry: GuidanceRegistry,
        cancellation_registry: CancellationRegistry,
    ) -> None:
        self.session_store = session_store
        self.event_store = event_store
        self.approval_registry = approval_registry
        self.guidance_registry = guidance_registry
        self.cancellation_registry = cancellation_registry
        self._active_threads: dict[str, threading.Thread] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def prepare_run(self, research_input: dict) -> PreparedRun:
        """Validate input and create session. Does NOT start execution."""
        import uuid
        run_id = uuid.uuid4().hex[:12]
        session_id = uuid.uuid4().hex[:12]

        session = RunSession(
            run_id=run_id,
            session_id=session_id,
            research_topic=research_input.get("topic", ""),
            status="queued",
            metadata=research_input,
        )
        self.session_store.create(session)

        return PreparedRun(
            run_id=run_id,
            session_id=session_id,
            research_topic=research_input.get("topic", ""),
            goal=research_input.get("goal", ""),
            user_workspace_path=research_input.get("workspace_path"),
            session=session,
        )

    def launch_prepared(self, prepared: PreparedRun) -> None:
        """Start the pipeline on a background thread."""
        if prepared.run_id in self._active_threads:
            existing = self._active_threads[prepared.run_id]
            if existing.is_alive():
                raise RuntimeError(f"Run {prepared.run_id} is already active.")

        cancel = self.cancellation_registry.create(prepared.run_id)

        thread = threading.Thread(
            target=self._execute,
            args=(prepared, cancel),
            daemon=True,
            name=f"pipeline-{prepared.run_id}",
        )
        self._active_threads[prepared.run_id] = thread
        thread.start()

    def cancel_run(self, run_id: str) -> bool:
        """Signal cancellation. Returns False if run not found."""
        self.cancellation_registry.cancel(run_id)
        self.approval_registry.remove(run_id)
        self.guidance_registry.remove_all(run_id)
        return run_id in self._active_threads

    # ── Emit helper ───────────────────────────────────────────────────────────

    def _emit(
        self,
        run_id: str,
        event_type: str,
        message: str,
        metadata: Optional[dict] = None,
    ) -> None:
        event = RunEvent(
            run_id=run_id,
            session_id="",
            event_type=normalize_event_type(event_type),
            agent_name="pipeline",
            content=message,
            metadata=metadata or {},
        )
        try:
            self.event_store.append(run_id, event)
        except Exception:
            logger.exception("Failed to write event: %s", message[:100])

    def _make_emit_fn(self, run_id: str):
        def emit(event_type: str, message: str, metadata: Optional[dict] = None) -> None:
            self._emit(run_id, event_type, message, metadata)
        return emit

    # ── Pipeline execution ────────────────────────────────────────────────────

    def _execute(self, prepared: PreparedRun, cancel: CancellationToken) -> None:
        run_id = prepared.run_id
        emit = self._make_emit_fn(run_id)
        phases_completed: list[int] = []
        total_repairs = 0

        try:
            self.session_store.update(run_id, {"status": "running"})
            emit("SYSTEM_START", f"[V4 Pipeline] Starting run {run_id}", {"run_id": run_id})

            # ── Phase 0: Workspace setup ──────────────────────────────────────
            emit("PHASE_START", "[Phase 0] Setting up workspace", {"phase": 0})
            workspace = setup_workspace(
                research_topic=prepared.research_topic,
                user_path=prepared.user_workspace_path,
                run_id=run_id,
            )
            emit(
                "AGENT_MESSAGE",
                f"[Phase 0] Workspace ready: {workspace.workspace_dir}",
                {"phase": 0, "workspace_dir": workspace.workspace_dir},
            )

            # CheckpointManager / InjectionQueue 초기화
            from pipeline_config.constants import DEFAULT_OUTPUT_BASE
            cm = CheckpointManager(output_base=DEFAULT_OUTPUT_BASE)
            injection_queue = ContextInjectionQueue()
            checkpoint = cm.load(run_id)
            if checkpoint:
                injection_queue.load_from_list(cm.load_queue(run_id))
            start_phase = checkpoint["phase"] if checkpoint else 1
            if checkpoint:
                emit(
                    "AGENT_MESSAGE",
                    f"[Pipeline] Resuming from checkpoint: phase {start_phase}",
                    {"checkpoint_phase": start_phase},
                )

            if cancel.is_cancelled:
                self._finish(run_id, "failed", "Cancelled after Phase 0")
                return

            # ── PreflightClarifier: 실행 전 최대 4문항 확인 ────────────────────
            clarifier = PreflightClarifier()
            clarifier_llm = None  # Phase 0 단계라 llm 없이 기본 질문 사용
            preflight_answers = clarifier.run(
                run_id=run_id,
                research_topic=prepared.research_topic,
                plan_summary=prepared.goal or prepared.research_topic,
                guidance_registry=self.guidance_registry,
                emit=emit,
                llm=clarifier_llm,
            )
            emit(
                "AGENT_MESSAGE",
                "[Preflight] Clarification complete.",
                {"preflight_answers": preflight_answers},
            )
            emit(
                "PHASE_COMPLETE",
                "[Phase 0] Workspace setup complete.",
                {"phase": 0},
            )
            phases_completed.append(0)

            # preflight 답변을 goal에 병합
            if preflight_answers.get("extra_context"):
                prepared = PreparedRun(
                    run_id=prepared.run_id,
                    session_id=prepared.session_id,
                    research_topic=prepared.research_topic,
                    goal=(prepared.goal or "") + "\n" + preflight_answers.get("extra_context", ""),
                    user_workspace_path=prepared.user_workspace_path,
                    session=prepared.session,
                )

            # ── Phase 0b: 사용자 제공 데이터 조사(도구 기반) → manifest → goal 주입 ──
            # data_path가 있으면 폴더를 조사·압축해제·구조추론해 dataset_manifest를 만들고,
            # 실제 경로/컬럼/클래스를 planner/designer/coder에 주입한다(눈감은 codegen 방지).
            _md0 = getattr(prepared.session, "metadata", None) or {}
            _dp = str(_md0.get("data_path") or "").strip()
            _dd = str(_md0.get("data_description") or "").strip()
            if _dp:
                try:
                    from orchestration.dataset_ingestor import ingest, manifest_to_context
                    manifest = ingest(_dp, data_description=_dd, emit=emit)
                    # 해제/추론된 실제 데이터 루트를 이후 단계(phase3 CLI/DATA_DIR)가 쓰도록 반영
                    _md0["data_path"] = manifest.get("resolved_path") or _dp
                    _md0["dataset_manifest"] = manifest
                    try:
                        hp = Path(workspace.root_dir) / "handoff"
                        hp.mkdir(parents=True, exist_ok=True)
                        (hp / "dataset_manifest.json").write_text(
                            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                    except Exception:
                        logger.exception("dataset_manifest 저장 실패")
                    data_ctx = manifest_to_context(manifest)
                except Exception as exc:
                    logger.exception("Dataset ingest 실패: %s", exc)
                    data_ctx = (
                        f"USER-PROVIDED DATASET at path: {_dp} (use as dataset root; do NOT download). {_dd}"
                    ).strip()
                prepared = PreparedRun(
                    run_id=prepared.run_id,
                    session_id=prepared.session_id,
                    research_topic=prepared.research_topic,
                    goal=(prepared.goal or "") + "\n" + data_ctx,
                    user_workspace_path=prepared.user_workspace_path,
                    session=prepared.session,
                )
            elif _dd:
                prepared = PreparedRun(
                    run_id=prepared.run_id,
                    session_id=prepared.session_id,
                    research_topic=prepared.research_topic,
                    goal=(prepared.goal or "") + "\nUSER DATASET NOTE: " + _dd,
                    user_workspace_path=prepared.user_workspace_path,
                    session=prepared.session,
                )

            # ── Phase 1: Planning + Design + Approval ─────────────────────────
            if start_phase <= 1:
                plan_bundle = run_planning_phase(
                    research_topic=prepared.research_topic,
                    goal=prepared.goal,
                    workspace=workspace,
                    approval_registry=self.approval_registry,
                    emit=emit,
                )
                emit(
                    "PHASE_COMPLETE",
                    f"[Phase 1] Planning complete. "
                    f"{len(plan_bundle.designer.files)} files planned.",
                    {"phase": 1, "file_count": len(plan_bundle.designer.files)},
                )
                phases_completed.append(1)
                cm.save(run_id, 2, [], [])
            else:
                # 체크포인트에서 복원된 경우 — plan_bundle을 재구성해야 함
                # (현재는 Phase 1부터 재실행; 향후 plan_bundle 직렬화로 개선 가능)
                plan_bundle = run_planning_phase(
                    research_topic=prepared.research_topic,
                    goal=prepared.goal,
                    workspace=workspace,
                    approval_registry=self.approval_registry,
                    emit=emit,
                )

            if cancel.is_cancelled:
                self._finish(run_id, "failed", "Cancelled after Phase 1")
                return

            # ── Scaffold materialization (Fix A) ──────────────────────────────
            # V4 planning intentionally excludes stable files (main.py/cli.py/
            # artifacts.py/config_schema.py); the scaffold owns them so that
            # `results/result.json` is written DETERMINISTICALLY by the stable
            # main.py, regardless of how the Coder shapes experiment_impl.py.
            if start_phase <= 2:
                from workspace.scaffold_service import ScaffoldService
                profile_name = plan_bundle.planner.recommended_profile or "generic_script"
                scaffold_input = {
                    "research_topic": prepared.research_topic,
                    "research_goal": prepared.goal,
                    "profile": profile_name,
                }
                ws_struct = {
                    "files": [
                        {"path": f.path, "responsibility": f.responsibility, "symbols": f.exports}
                        for f in plan_bundle.designer.files
                        if f.mutable and not f.path.startswith("src/main")
                    ],
                    "generation_order": plan_bundle.designer.generation_order,
                }
                scaffold_svc = ScaffoldService()
                pending = scaffold_svc.materialize_stable_only(
                    output_path=Path(workspace.root_dir),
                    research_input=scaffold_input,
                    profile_name=profile_name,
                )
                scaffold_svc.finalize_with_designer_output(pending, ws_struct)
                # Entry point is now the scaffold-owned stable main.py
                plan_bundle.designer.entry_point = "src/main.py"
                emit(
                    "AGENT_MESSAGE",
                    f"[Scaffold] Stable files + run_contract materialized (profile={profile_name})",
                    {"phase": 2, "profile": profile_name, "entry_point": "src/main.py"},
                )

            # ── Phase 2: Staged Coding ────────────────────────────────────────
            if start_phase <= 2:
                coding_result = run_coding_phase(
                    plan=plan_bundle,
                    guidance_registry=self.guidance_registry,
                    emit=emit,
                    cancel=cancel,
                )
                emit(
                    "PHASE_COMPLETE",
                    f"[Phase 2] Coding complete. "
                    f"Smoke test: {'PASSED' if coding_result.smoke_test_passed else 'FAILED'}",
                    {"phase": 2, "smoke_test": coding_result.smoke_test_passed},
                )
                phases_completed.append(2)
                # Phase 2 완료된 파일 목록 수집
                done_files = [
                    fr.path
                    for stage in coding_result.stages
                    for fr in stage.files
                    if fr.written
                ]
                total_repairs += sum(
                    len(fr.repair_records)
                    for stage in coding_result.stages
                    for fr in stage.files
                )
                cm.save(run_id, 3, done_files, [])
            else:
                coding_result = None  # 재구성 불가 — Phase 3부터 재개 시 임시 처리

            if cancel.is_cancelled:
                self._finish(run_id, "failed", "Cancelled after Phase 2")
                return

            # ── Phase 3: Experiment Execution ─────────────────────────────────
            if start_phase <= 3:
                failure_detector = FailurePatternDetector()
                # P1-3: 설정 시점에 선택된 실행 환경(python 실행파일)을 사용한다.
                # 미지정 시 현재 서버 인터프리터로 실행(phase3가 폴백 처리).
                run_env_python = None
                run_data_path = None
                try:
                    _md = getattr(prepared.session, "metadata", None) or {}
                    run_env_python = _md.get("environment") or None
                    run_data_path = (str(_md.get("data_path") or "").strip() or None)
                except Exception:
                    run_env_python = None
                    run_data_path = None
                # ── P1: 성능 추구 개선 루프 (완주→성능추구) ─────────────────────
                # 정량 목표(success_criteria)가 있으면 달성 시 조기 종료, 없으면 성능이
                # 정체될 때까지 학습 예산(epoch)을 증대하며 재실행하고 best-so-far를 넘긴다.
                # (에폭 레버가 없는 tabular 등은 단일 실행.)
                from orchestration.target_gate import parse_targets, primary_metric, evaluate, is_better
                from phases.phase3_execution import _planned_epochs
                targets = parse_targets(plan_bundle.planner.success_criteria)
                base_epochs = _planned_epochs(plan_bundle)
                try:
                    max_iters = max(1, min(int(_md.get("max_experiments") or 3), 5))
                except Exception:
                    max_iters = 3
                EPOCH_CAP, PLATEAU_EPS = 30, 0.02
                best_exec, best_val, prev_val, cur_epochs = None, None, None, base_epochs
                for _it in range(max_iters):
                    exec_result = run_execution_phase(
                        plan=plan_bundle,
                        coding_result=coding_result,
                        guidance_registry=self.guidance_registry,
                        emit=emit,
                        cancel=cancel,
                        python_exe=run_env_python,
                        data_path=run_data_path,
                        epochs_override=cur_epochs,
                    )
                    if cancel.is_cancelled or not exec_result.success:
                        best_exec = best_exec or exec_result
                        break
                    pm = primary_metric(exec_result.metrics)
                    gate = evaluate(exec_result.metrics, targets)
                    if pm is not None:
                        _name, _val, _higher = pm
                        if is_better(_val, best_val, _higher):
                            best_exec, best_val = exec_result, _val
                        emit(
                            "AGENT_MESSAGE",
                            f"[Phase 3] 개선 루프 {_it + 1}/{max_iters}: {_name}={_val:.4f} "
                            f"({gate['status']}), best={best_val:.4f}, epochs={cur_epochs}",
                            {"iter": _it + 1, "primary": _name, "value": _val,
                             "gate": gate["status"], "epochs": cur_epochs},
                        )
                    else:
                        best_exec = best_exec or exec_result
                    if gate["status"] == "met":
                        emit("AGENT_MESSAGE",
                             f"[Phase 3] 성능 목표 달성 — 조기 종료. {gate['detail']}",
                             {"target_met": True})
                        break
                    if not base_epochs or _it >= max_iters - 1:
                        break  # 에폭 레버 없음(tabular) 또는 예산 소진
                    if pm is not None and prev_val is not None:
                        rel = abs(_val - prev_val) / (abs(prev_val) + 1e-9)
                        if rel < PLATEAU_EPS:
                            emit("AGENT_MESSAGE",
                                 f"[Phase 3] 성능 정체(직전 대비 {rel * 100:.1f}% 개선) — 예산 증대 중단",
                                 {"plateau": True})
                            break
                    if pm is not None:
                        prev_val = _val
                    cur_epochs = min((cur_epochs or 1) * 3, EPOCH_CAP)
                    emit("AGENT_MESSAGE",
                         f"[Phase 3] 추가 개선 여지 → 학습 예산 {cur_epochs} epoch로 재실행",
                         {"next_epochs": cur_epochs})
                exec_result = best_exec or exec_result

                # 실패 시 패턴 감지 (escalation 판단은 run_execution_phase 내부에서 이미 처리)
                if not exec_result.success:
                    kind = failure_detector.record(exec_result.stderr_tail, exec_result.return_code)
                    if failure_detector.should_escalate():
                        emit(
                            "failure_escalation",
                            f"[FailureDetector] Repeated failure pattern detected: "
                            f"{failure_detector.summary()}",
                            {"pattern_summary": failure_detector.summary(), "kind": kind.value},
                        )
                emit(
                    "PHASE_COMPLETE",
                    f"[Phase 3] Execution {'succeeded' if exec_result.success else 'failed'}. "
                    f"Metrics: {list(exec_result.metrics.keys())[:5]}",
                    {"phase": 3, "success": exec_result.success, "metrics": exec_result.metrics},
                )
                phases_completed.append(3)
                cm.save(run_id, 4, [], [])

            if cancel.is_cancelled:
                self._finish(run_id, "failed", "Cancelled after Phase 3")
                return

            # ── Phase 4: Paper Writing ────────────────────────────────────────
            writing_result = run_writing_phase(
                plan=plan_bundle,
                exec_result=exec_result,
                emit=emit,
            )
            emit(
                "PHASE_COMPLETE",
                f"[Phase 4] Paper written: {writing_result.paper_path}",
                {"phase": 4, "paper_path": writing_result.paper_path,
                 "quality": writing_result.overall_quality},
            )
            phases_completed.append(4)

            # ── ExtensionProposer: 추가 실험 제안 (실행은 사용자 결정) ─────────
            try:
                from orchestration.context_compressor import ContextCompressor
                compressor = ContextCompressor()
                exec_summary = compressor.compress_executor_result(exec_result)
                proposer = ExtensionProposer()
                proposer.propose(
                    exec_summary=exec_summary,
                    analysis_summary="",
                    emit=emit,
                )
            except Exception:
                logger.exception("ExtensionProposer failed for %s", run_id)

            # ── Done ──────────────────────────────────────────────────────────
            result_summary = {
                "paper_path": writing_result.paper_path,
                "workspace_dir": workspace.workspace_dir,
                "exec_success": exec_result.success,
                "metrics": exec_result.metrics,
                "paper_quality": writing_result.overall_quality,
                # P1-3: 재현성 메타데이터(실행 환경/버전/패키지 지문/entry_command)
                "environment": getattr(exec_result, "environment", {}) or {},
            }
            self._finish(
                run_id, "completed",
                output_path=workspace.root_dir,
                result_summary=result_summary,
                phases_completed=phases_completed,
                total_repairs=total_repairs,
                paper_path=writing_result.paper_path,
            )
            cm.clear(run_id)
            emit("SYSTEM_END", f"[V4 Pipeline] Run {run_id} completed.", result_summary)

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Pipeline error for %s: %s\n%s", run_id, exc, tb)
            emit("SYSTEM_END", f"[V4 Pipeline] Run {run_id} failed: {exc}", {"error": str(exc)})
            self._finish(run_id, "failed", error=str(exc))
        finally:
            self.cancellation_registry.remove(run_id)
            self.guidance_registry.remove_all(run_id)
            self.approval_registry.remove(run_id)

    def _finish(
        self,
        run_id: str,
        status: str,
        error: str = "",
        output_path: str = "",
        result_summary: Optional[dict] = None,
        phases_completed: Optional[list] = None,
        total_repairs: int = 0,
        paper_path: str = "",
    ) -> None:
        try:
            patch: dict = {"status": status}
            if error:
                patch["error"] = error
            if output_path:
                patch["output_path"] = output_path
            if result_summary is not None:
                patch["result_summary"] = result_summary
            self.session_store.update(run_id, patch)
        except Exception:
            logger.exception("Failed to update session status for %s", run_id)

        # run_summary.json 을 output_path 디렉토리에 저장
        if output_path:
            try:
                summary = {
                    "run_id": run_id,
                    "status": status,
                    "completed_at": datetime.now(tz=timezone.utc).isoformat(),
                    "phases_completed": phases_completed or [],
                    "total_repair_attempts": total_repairs,
                    "output_paper_path": paper_path,
                    "error": error,
                }
                summary_path = Path(output_path) / "run_summary.json"
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            except Exception:
                logger.exception("Failed to write run_summary.json for %s", run_id)
