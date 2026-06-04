"""entrypoints/init.py — Runtime initialization for the V4 pipeline."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from orchestration.approval_registry import (
    ApprovalRegistry,
    CancellationRegistry,
    GuidanceRegistry,
)
from orchestration.pipeline_orchestrator import PipelineOrchestrator
from runtime.event_store import EventStore
from runtime.run_repository import RunRepository
from runtime.session_store import SessionStore
from runtime.state_calculator import StateCalculator
from runtime.stream_service import StreamService


@dataclass(slots=True)
class AppServices:
    """Initialized services shared by the FastAPI app (V4)."""

    project_root: Path
    output_root: Path
    session_store: SessionStore
    event_store: EventStore
    run_repository: RunRepository
    state_calculator: StateCalculator
    stream_service: StreamService
    approval_registry: ApprovalRegistry
    guidance_registry: GuidanceRegistry
    cancellation_registry: CancellationRegistry
    coordinator: PipelineOrchestrator


def _cleanup_stale_sessions(session_store: SessionStore) -> None:
    """서버 재시작 시 running/queued 상태로 남은 고아 세션을 interrupted로 전환."""
    try:
        stale = [s for s in session_store.list() if s.status in ("running", "queued")]
        for session in stale:
            session_store.update(session.run_id, {"status": "interrupted"})
        if stale:
            print(f"[runtime] 고아 세션 {len(stale)}개 → interrupted 처리됨")
    except Exception as exc:
        print(f"[runtime] WARNING: 고아 세션 정리 실패: {exc}")


def initialize_runtime(project_root: Path | None = None) -> AppServices:
    """Build the V4 service graph."""
    resolved_root = project_root or Path(__file__).resolve().parents[1]
    output_root = resolved_root / "outputs"
    runs_root = resolved_root / "runs"
    output_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)

    # Shared stores
    session_store = SessionStore(runs_root)
    event_store = EventStore(runs_root)
    run_repository = RunRepository(session_store)
    state_calculator = StateCalculator()
    stream_service = StreamService(session_store, event_store, run_repository, state_calculator)

    # V4 registries
    approval_registry = ApprovalRegistry()
    guidance_registry = GuidanceRegistry()
    cancellation_registry = CancellationRegistry()

    # Pipeline orchestrator
    coordinator = PipelineOrchestrator(
        session_store=session_store,
        event_store=event_store,
        approval_registry=approval_registry,
        guidance_registry=guidance_registry,
        cancellation_registry=cancellation_registry,
    )

    _cleanup_stale_sessions(session_store)

    print(f"[runtime V4] project_root={resolved_root}")
    print(f"[runtime V4] python={sys.executable}")
    print(f"[runtime V4] coordinator=PipelineOrchestrator")

    return AppServices(
        project_root=resolved_root,
        output_root=output_root,
        session_store=session_store,
        event_store=event_store,
        run_repository=run_repository,
        state_calculator=state_calculator,
        stream_service=stream_service,
        approval_registry=approval_registry,
        guidance_registry=guidance_registry,
        cancellation_registry=cancellation_registry,
        coordinator=coordinator,
    )
