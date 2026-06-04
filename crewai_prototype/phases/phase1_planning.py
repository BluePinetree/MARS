"""phases/phase1_planning.py — Planner + Designer + User Approval Gate (Phase 1).

Flow:
  1. PlannerAgent  → PlannerResult JSON
  2. DesignerAgent → DesignerResultV4 JSON
  3. Emit PLAN_AWAITING_APPROVAL event
  4. Block on ApprovalGate.wait()
  5a. APPROVE  → return PlanBundle
  5b. MODIFY / REJECT → inject feedback, go to step 1
  Repeat up to MAX_REPLAN_ROUNDS times, then auto-approve with warning.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from crewai import Agent, Crew, Task

from core.handoff_models import (
    DesignerResultV4,
    FileNodeSpec,
    PlanBundle,
    PlannerResult,
    WorkspaceConfig,
)
from core.json_extractor import extract_json_object as extract_json
from core.llm_factory import create_llm_for_agent
from orchestration.approval_registry import ApprovalGate, ApprovalRegistry
from pipeline_config.constants import (
    APPROVAL_TIMEOUT_SECS,
    DESIGNER_MAX_ITER,
    MAX_REPLAN_ROUNDS,
    PLANNER_MAX_ITER,
)

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]


# ── Task descriptions ─────────────────────────────────────────────────────────

_PLANNER_TASK = """\
Research topic: {research_topic}
Goal: {goal}
Prior feedback from user (empty if first attempt): {feedback}

Produce a JSON object with exactly these keys:
  problem_statement   (str)
  research_questions  (list[str], 2–5 items)
  hypotheses          (list[str])
  success_criteria    (list[str], measurable)
  constraints         (list[str])
  risks               (list[{{risk: str, mitigation: str}}])
  recommended_profile (str: "vision_classification" | "tabular_supervised" |
                        "timeseries_forecasting" | "generic_script")
  next_stage_inputs   (dict[str, str])

Output ONLY the JSON object. No prose."""

_DESIGNER_TASK = """\
Research plan:
{plan_json}

Design the workspace file structure. Produce a JSON object with exactly these keys:
  experiment_family   (str)
  entry_point         (str: relative path to main script, e.g. "src/main.py")
  files               (list of file specs)
  generation_order    (list[str]: file paths in dependency order — leaf files first)
  stage_assignments   (dict: file_path → stage int 1/2/3)
  import_graph        (dict: file_path → [file_paths it imports from])
  success_criteria    (list[str])
  notes               (list[str])

Each file spec in "files":
  path           (str: relative to workspace/, e.g. "src/datasets.py")
  responsibility (str: one sentence)
  exports        (list[str]: function/class names this file exposes)
  imports_from   (list[str]: other workspace files it imports from)
  stage          (int: 1=config/utils, 2=data/model/trainer, 3=entry point)
  mutable        (bool: true for files the Coder must write)

Stage rules:
  Stage 1 — no imports from other mutable files (pure config, utils, constants)
  Stage 2 — may import Stage-1 files only
  Stage 3 — the main entry point; may import Stages 1 and 2

Do NOT include stable scaffold files (src/main.py, src/cli.py, src/artifacts.py,
src/config_schema.py) — only mutable domain files.
Output ONLY the JSON object. No prose."""


# ── Agent builders ────────────────────────────────────────────────────────────

def _make_planner(llm) -> Agent:
    return Agent(
        role="AI Research Planner",
        goal=(
            "Transform a research topic into a concrete, actionable experiment plan. "
            "Identify the primary metric, recommend a scaffold profile, and list measurable "
            "success criteria. Output structured JSON only."
        ),
        backstory=(
            "You are a senior AI research planner with 15 years of experience designing ML "
            "experiments. You scope problems precisely, choose the right metrics, and identify "
            "risks early. You always output structured JSON — never prose."
        ),
        llm=llm,
        tools=[],
        verbose=True,
        allow_delegation=False,
        max_iter=PLANNER_MAX_ITER,
    )


def _make_designer(llm) -> Agent:
    return Agent(
        role="Experiment Designer",
        goal=(
            "Convert a research plan into a precise file-by-file workspace structure with "
            "AST-level detail: exports, imports, stage assignments, and dependency order. "
            "Output structured JSON only."
        ),
        backstory=(
            "You are an ML systems architect specialising in experiment scaffolding. "
            "You know exactly which Python files a research codebase needs, what each file "
            "must export, which stage it belongs to, and in what order to generate them. "
            "You never include stable scaffold files — only mutable domain files."
        ),
        llm=llm,
        tools=[],
        verbose=True,
        allow_delegation=False,
        max_iter=DESIGNER_MAX_ITER,
    )


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse_planner_result(raw: str) -> PlannerResult:
    data = extract_json(raw)
    if not data:
        logger.warning("PlannerResult: no JSON found, using defaults. raw=%s", raw[:200])
        return PlannerResult(problem_statement=raw[:500])
    if isinstance(data, list):
        data = data[0]
    return PlannerResult.model_validate(data)


def _parse_designer_result(raw: str) -> DesignerResultV4:
    data = extract_json(raw)
    if not data:
        logger.warning("DesignerResult: no JSON found. raw=%s", raw[:200])
        return DesignerResultV4()
    if isinstance(data, list):
        data = data[0]
    return DesignerResultV4.model_validate(data)


# ── Phase 1 main function ─────────────────────────────────────────────────────

def run_planning_phase(
    research_topic: str,
    goal: str,
    workspace: WorkspaceConfig,
    approval_registry: ApprovalRegistry,
    emit: EmitFn,
    llm=None,
) -> PlanBundle:
    """Run Planner + Designer, then block until user approves.

    Loops up to MAX_REPLAN_ROUNDS if the user rejects or requests modifications.
    Auto-approves with a warning if no response within APPROVAL_TIMEOUT_SECS.

    Args:
        research_topic:     The user's research question.
        goal:               Optional elaboration of the goal.
        workspace:          Phase 0 output.
        approval_registry:  Shared registry; API layer resolves the gate.
        emit:               Callable(event_type, message, metadata).
        llm:                CrewAI LLM instance.

    Returns:
        Approved PlanBundle.
    """
    planner_llm = create_llm_for_agent("research_planner")
    designer_llm = create_llm_for_agent("experiment_designer")

    feedback = ""

    for round_no in range(1, MAX_REPLAN_ROUNDS + 1):
        emit("PHASE_START", f"[Phase 1] Round {round_no} — planning & design", {"round": round_no})

        # ── Step 1: Planner ───────────────────────────────────────────────────
        planner_task = Task(
            description=_PLANNER_TASK.format(
                research_topic=research_topic,
                goal=goal or research_topic,
                feedback=feedback or "(none)",
            ),
            expected_output="A JSON object matching the PlannerResult schema.",
            agent=_make_planner(planner_llm),
        )
        planner_crew = Crew(agents=[planner_task.agent], tasks=[planner_task], verbose=False)
        planner_output = planner_crew.kickoff()
        planner_raw = getattr(planner_output, "raw", "") or str(planner_output)
        planner_result = _parse_planner_result(planner_raw)

        emit(
            "AGENT_MESSAGE",
            f"[Planner] Plan ready: {planner_result.problem_statement[:120]}",
            {"agent_tag": "Planner", "action": "plan_ready", "round": round_no},
        )

        # ── Step 2: Designer ──────────────────────────────────────────────────
        designer_task = Task(
            description=_DESIGNER_TASK.format(
                plan_json=planner_result.model_dump_json(indent=2),
            ),
            expected_output="A JSON object matching the DesignerResultV4 schema.",
            agent=_make_designer(designer_llm),
        )
        designer_crew = Crew(agents=[designer_task.agent], tasks=[designer_task], verbose=False)
        designer_output = designer_crew.kickoff()
        designer_raw = getattr(designer_output, "raw", "") or str(designer_output)
        designer_result = _parse_designer_result(designer_raw)

        emit(
            "AGENT_MESSAGE",
            f"[Designer] File tree ready: {len(designer_result.files)} files, "
            f"entry point: {designer_result.entry_point}",
            {"agent_tag": "Designer", "action": "design_ready", "round": round_no,
             "file_count": len(designer_result.files)},
        )

        # Persist to handoff store
        handoff_dir = Path(workspace.handoff_dir)
        (handoff_dir / "planner_result.json").write_text(
            planner_result.model_dump_json(indent=2), encoding="utf-8"
        )
        (handoff_dir / "designer_result.json").write_text(
            designer_result.model_dump_json(indent=2), encoding="utf-8"
        )

        # ── Step 3: Approval gate ─────────────────────────────────────────────
        bundle = PlanBundle(
            planner=planner_result,
            designer=designer_result,
            workspace=workspace,
        )
        gate = ApprovalGate(plan_payload=bundle.model_dump())
        approval_registry.register(workspace.run_id, gate)

        emit(
            "PLAN_AWAITING_APPROVAL",
            f"[Phase 1] Plan ready — waiting for your approval (timeout {APPROVAL_TIMEOUT_SECS}s)",
            {
                "run_id": workspace.run_id,
                "round": round_no,
                "plan": bundle.model_dump(),
                "timeout_secs": APPROVAL_TIMEOUT_SECS,
            },
        )

        resolved = gate.wait(timeout=APPROVAL_TIMEOUT_SECS)

        approval_registry.remove(workspace.run_id)

        if not resolved:
            emit(
                "AGENT_MESSAGE",
                f"[Phase 1] Approval timeout — auto-approving plan (round {round_no})",
                {"auto_approved": True, "round": round_no},
            )
            return bundle

        if gate.is_approved:
            emit(
                "AGENT_MESSAGE",
                "[Phase 1] Plan approved by user.",
                {"approved": True, "round": round_no},
            )
            return bundle

        # REJECT — hard stop, do not re-plan
        if gate.action == "reject":
            reason = gate.feedback or "User rejected the plan."
            emit(
                "AGENT_MESSAGE",
                f"[Phase 1] Plan rejected by user: {reason[:200]}",
                {"rejected": True, "round": round_no, "reason": reason},
            )
            raise RuntimeError(f"[Phase 1] Research plan rejected by user: {reason}")

        # MODIFY — inject feedback and re-plan
        feedback = gate.feedback or "User requested modifications. Please revise."
        emit(
            "AGENT_MESSAGE",
            f"[Phase 1] Plan not approved. Feedback: {feedback[:200]}. "
            f"Re-planning (round {round_no}/{MAX_REPLAN_ROUNDS}).",
            {"feedback": feedback, "round": round_no},
        )

    # Exhausted replan rounds — use last plan
    emit(
        "AGENT_MESSAGE",
        f"[Phase 1] Max replan rounds ({MAX_REPLAN_ROUNDS}) exhausted — using last plan.",
        {"auto_approved": True, "exhausted": True},
    )
    return PlanBundle(
        planner=planner_result,      # type: ignore[possibly-undefined]
        designer=designer_result,    # type: ignore[possibly-undefined]
        workspace=workspace,
    )
