"""pipeline_config/constants.py — All configurable constants for the V4 pipeline.

Every constant is readable from an environment variable:
  RESEARCH_PIPELINE_<NAME>   (uppercase, underscores)

Examples:
  RESEARCH_PIPELINE_MAX_AUTO_REPAIR_ATTEMPTS=10 python main.py
"""

from __future__ import annotations

import os


def _env(name: str, default):
    """Read RESEARCH_PIPELINE_<name> from env, cast to type of default."""
    raw = os.environ.get(f"RESEARCH_PIPELINE_{name.upper()}")
    if raw is None:
        return default
    try:
        return type(default)(raw)
    except (ValueError, TypeError):
        return default


# ── Phase 2: Staged Coding ────────────────────────────────────────────────────

# Max automatic repair attempts before escalating to user.
# Range: 1–50. Higher = fewer interruptions, more LLM cost.
MAX_AUTO_REPAIR_ATTEMPTS: int = _env("MAX_AUTO_REPAIR_ATTEMPTS", 5)

# Seconds to wait for user guidance before resuming with no hint.
# Range: 60–86400. Default 2 hours.
USER_GUIDANCE_TIMEOUT_SECS: int = _env("USER_GUIDANCE_TIMEOUT_SECS", 7200)

# Max iterations per file coder agent kickoff.
# Range: 5–50. High values allow more tool calls per turn.
CODER_MAX_ITER: int = _env("CODER_MAX_ITER", 20)

# ── Phase 1: Approval Gate ────────────────────────────────────────────────────

# Seconds to wait for plan approval before auto-approving.
# Range: 60–86400. Default 1 hour.
APPROVAL_TIMEOUT_SECS: int = _env("APPROVAL_TIMEOUT_SECS", 3600)

# Max number of replanning rounds when user rejects the plan.
# Range: 1–10.
MAX_REPLAN_ROUNDS: int = _env("MAX_REPLAN_ROUNDS", 5)

# ── Phase 3: Experiment Execution ─────────────────────────────────────────────

# Subprocess timeout per experiment run in seconds.
# Range: 60–86400. Default 90 minutes.
EXPERIMENT_TIMEOUT_SECS: int = _env("EXPERIMENT_TIMEOUT_SECS", 5400)

# Max execution retry attempts (same escalation pattern as coding).
MAX_EXEC_REPAIR_ATTEMPTS: int = _env("MAX_EXEC_REPAIR_ATTEMPTS", 3)

# 개선 outer loop가 학습 예산을 증대할 때의 상한 하한선.
# 실제 상한은 max(계획 epochs, 이 값) — 계획보다 낮은 상한은 강등을 뜻하므로 금지한다.
# (실측: 하드코딩 30 + 계획 200이면 2회차가 30으로 강등되어 재실행이 무의미해졌다.)
EPOCH_ESCALATION_CAP: int = _env("EPOCH_ESCALATION_CAP", 30)

# 계획 epochs가 이 값 이상이면 이미 문헌 수준 예산이므로 "예산 증대" 레버를 끈다
# (개선 루프를 단일 실행으로 고정). 벤치마크 모드의 max_improvement_iterations=1과 정합.
LONG_RUN_EPOCH_THRESHOLD: int = _env("LONG_RUN_EPOCH_THRESHOLD", 100)

# 실험 서브프로세스가 아무 출력도 내지 않은 채 이 시간을 넘기면 교착/좀비로 보고
# 프로세스 트리를 종료한다. EXPERIMENT_TIMEOUT_SECS를 크게 올릴 때 반드시 함께 켜야 한다
# (타임아웃만 올리면 "90분에 죽는 문제"가 "수십 시간 매달리는 문제"로 바뀐다).
STALL_TIMEOUT_SECS: int = _env("STALL_TIMEOUT_SECS", 3600)

# 실험 서브프로세스가 살아있음을 알리는 하트비트 이벤트 주기(초).
# 생성 코드가 stdout에 아무것도 찍지 않아도 진행 상황이 보이게 한다.
EXPERIMENT_HEARTBEAT_SECS: int = _env("EXPERIMENT_HEARTBEAT_SECS", 300)

# Total wall-clock timeout for the smoke test repair loop (seconds).
# Prevents infinite repair spin when entry point repeatedly fails.
MAX_SMOKE_TOTAL_SECS: int = _env("MAX_SMOKE_TOTAL_SECS", 300)

# Persistent dataset cache directory shared across all runs.
# Phase 3 injects this as DATA_DIR env var so generated code can reuse downloaded datasets.
# Example: RESEARCH_PIPELINE_DATA_CACHE_DIR=C:/Users/yunsu/.cache/mars_datasets
DATA_CACHE_DIR: str = _env("DATA_CACHE_DIR", "")

# ── Phase 4: Paper Writing ────────────────────────────────────────────────────

# Max revision attempts per paper section before marking NEEDS_REVIEW.
MAX_SECTION_REVISIONS: int = _env("MAX_SECTION_REVISIONS", 3)

# Quality threshold (0.0–1.0). Sections below this score get rewritten.
SECTION_QUALITY_THRESHOLD: float = _env("SECTION_QUALITY_THRESHOLD", 0.70)

# Minimum word counts per section.
SECTION_MIN_WORDS: dict[str, int] = {
    "Introduction":     300,
    "Related_Works":    400,
    "Proposed_Method":  500,
    "Experiments":      600,
    "Conclusion":       200,
    "References":       100,
    "Abstract":         150,
}

# Writer agent max iterations per section.
WRITER_MAX_ITER: int = _env("WRITER_MAX_ITER", 5)

# ── LLM / CrewAI ─────────────────────────────────────────────────────────────

# Planner / Designer agent max iterations.
PLANNER_MAX_ITER: int = _env("PLANNER_MAX_ITER", 3)
DESIGNER_MAX_ITER: int = _env("DESIGNER_MAX_ITER", 3)

# Executor agent max iterations.
EXECUTOR_MAX_ITER: int = _env("EXECUTOR_MAX_ITER", 5)

# ── Output Paths ──────────────────────────────────────────────────────────────

# Default base directory for run outputs (relative to crewai_prototype/).
DEFAULT_OUTPUT_BASE: str = _env("DEFAULT_OUTPUT_BASE", "outputs")
