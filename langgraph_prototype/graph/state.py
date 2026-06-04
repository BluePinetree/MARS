"""
Shared state schema for the LangGraph research workflow.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class ExperimentResult(TypedDict, total=False):
    """Single experiment execution result."""

    experiment_id: str
    metrics: dict
    wandb_run_url: str
    docker_logs: str
    logs_summary: str
    logs_path: str
    artifacts_dir: str
    success: bool
    error_message: str


class DebugInfo(TypedDict, total=False):
    """Debug loop metadata."""

    loop_count: int
    max_loops: int
    error_analysis: str
    fix_suggestion: str
    discussion_points: list[str]
    missing_checks: list[str]


class ResearchInput(TypedDict, total=False):
    """Input payload for a research run."""

    research_topic: str
    research_goal: str
    research_domain: str
    data_path: str
    data_description: str
    constraints: dict
    output_path: str


class ResearchState(TypedDict, total=False):
    """Global state object shared across all graph nodes."""

    research_input: ResearchInput

    session_id: str
    run_id: str

    plan: str
    literature_review: str

    design: str
    hypothesis: str
    methodology: str

    code: str
    code_requirements: str
    code_description: str

    experiment_results: Annotated[list[ExperimentResult], add]
    current_experiment_id: str

    analysis: str
    meets_target: bool
    best_metrics: dict

    report: str
    report_path: str

    latest_analysis_json_path: str
    handoff_state_path: str

    prompt_token_count_estimate: int
    failure_diagnostics: dict

    context_char_budget: int
    context_token_budget: int
    compact_max_chars: int

    debug_info: DebugInfo

    current_phase: str
    phase_history: Annotated[list[str], add]
    error: str
    status: str

    # ── 플랫폼 통합 신규 필드 ─────────────────────────────────────────────
    workspace_root: str           # 런타임에 scaffold 후 설정
    mutable_files: str            # numbered list (coder 프롬프트용)
    missing_files: list           # pre-flight 결과 (str list)
    code_status: str              # "complete" | "incomplete" | "not_started"
    repair_needed: bool           # analyzer → coder repair 라우팅
    repair_actions: list          # analyzer가 제안한 수리 대상 [{path, reason}]
    coder_messages: list          # run_tool_loop 전체 히스토리 (디버그)
    executor_messages: list       # run_tool_loop 전체 히스토리 (디버그)
    telemetry_path: str           # telemetry.jsonl 절대 경로
    latest_execution_success: bool  # 최신 실행 성공 여부


def create_initial_state(
    research_input: ResearchInput,
    session_id: str,
    run_id: str,
    max_loops: int = 3,
    context_char_budget: int = 24000,
    context_token_budget: int = 6000,
    compact_max_chars: int = 2000,
    workspace_root: str = "",
) -> ResearchState:
    """Create initial state for a run."""

    return ResearchState(
        research_input=research_input,
        session_id=session_id,
        run_id=run_id,
        plan="",
        literature_review="",
        design="",
        hypothesis="",
        methodology="",
        code="",
        code_requirements="",
        code_description="",
        experiment_results=[],
        current_experiment_id="",
        analysis="",
        meets_target=False,
        best_metrics={},
        report="",
        report_path="",
        latest_analysis_json_path="",
        handoff_state_path="",
        prompt_token_count_estimate=0,
        failure_diagnostics={},
        context_char_budget=int(context_char_budget),
        context_token_budget=int(context_token_budget),
        compact_max_chars=int(compact_max_chars),
        debug_info=DebugInfo(
            loop_count=0,
            max_loops=max(1, int(max_loops)),
            error_analysis="",
            fix_suggestion="",
            discussion_points=[],
            missing_checks=[],
        ),
        current_phase="initial",
        phase_history=["initial"],
        error="",
        status="running",
        workspace_root=workspace_root,
        mutable_files="",
        missing_files=[],
        code_status="not_started",
        repair_needed=False,
        repair_actions=[],
        coder_messages=[],
        executor_messages=[],
        telemetry_path="",
        latest_execution_success=False,
    )
