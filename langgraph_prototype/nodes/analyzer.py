"""Result Analyzer node — Anthropic SDK 직접 사용."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_RSP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_RSP_ROOT))

try:
    from rsp.with_retry import with_retry
    from rsp.telemetry import NodeEvent, TelemetryStore
    _RSP_AVAILABLE = True
except Exception:
    _RSP_AVAILABLE = False
    def with_retry(fn, *args, **kwargs):
        return fn(*args, **kwargs)

from graph.state import ResearchState
from nodes.base import (
    get_research_context,
    persist_handoff_state,
    save_text_artifact,
    update_phase,
)


ANALYZER_SYSTEM_PROMPT = """You are the Result Analyzer for an autonomous ML research loop.

Analyze the latest execution outcome and produce:
1) performance summary
2) anomalies / suspicious behavior
3) missing checks that should be verified next
4) concrete next-step fix suggestions
5) final decision token: DECISION: TARGET_MET or DECISION: NEEDS_IMPROVEMENT
"""


def create_analyzer_node(client, model: str, logger=None, wandb_tool=None, settings=None):
    target_accuracy = settings.target_accuracy if settings else 0.90

    def analyzer_node(state: ResearchState) -> dict:
        agent_name = "Result Analyzer"
        if logger:
            logger.log_agent_thinking(agent_name, "Analyzing latest execution and deciding next step.")

        results = state.get("experiment_results", [])
        latest = results[-1] if results else {}

        wandb_details = ""
        if wandb_tool and latest.get("wandb_run_url"):
            try:
                if logger:
                    logger.log_tool_call(agent_name, "wandb_api", {"run_url": latest.get("wandb_run_url", "")})
                detailed = wandb_tool.get_detailed_metrics(latest.get("experiment_id", ""))
                wandb_details = f"\n\n## W&B detailed metrics\n{detailed}"
                if logger:
                    logger.log_tool_result(agent_name, "Loaded W&B detailed metrics.", success=True)
            except Exception as exc:
                if logger:
                    logger.log_tool_result(agent_name, f"Failed to load W&B metrics: {exc}", success=False)

        research_context = get_research_context(state, agent_name=agent_name, logger=logger)
        latest_result_summary = (
            f"latest_result: success={latest.get('success')} "
            f"metrics={latest.get('metrics', {})} "
            f"logs_path={latest.get('logs_path', '')}"
        )

        user_prompt = (
            f"{research_context}\n\n"
            f"{latest_result_summary}{wandb_details}\n\n"
            f"Target accuracy: {target_accuracy}\n\n"
            "Review the latest run and provide a strict go/no-go decision token."
        )

        t0 = time.time()
        response = with_retry(
            client.messages.create,
            model=model,
            system=ANALYZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=2048,
        )
        analysis_text = response.content[0].text

        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="analyzer",
                    phase="exit",
                    tokens_in=response.usage.input_tokens,
                    tokens_out=response.usage.output_tokens,
                    duration_ms=(time.time() - t0) * 1000,
                ))
            except Exception:
                pass

        meets_target = _check_target_met(analysis_text, results, target_accuracy)
        best_metrics = _get_best_metrics(results)

        discussion_points = _extract_bullets(
            analysis_text,
            keywords=["anomaly", "issue", "risk", "concern", "discussion", "debate", "suspicious"],
        )
        missing_checks = _extract_bullets(
            analysis_text,
            keywords=["missing", "check", "not verified", "validation", "ablation", "sanity check"],
        )

        analysis_summary = _summarize_analysis(analysis_text)
        iteration = len(results)
        analysis_payload = {
            "iteration": iteration,
            "target_accuracy": target_accuracy,
            "meets_target": meets_target,
            "best_metrics": best_metrics,
            "discussion_points": discussion_points,
            "missing_checks": missing_checks,
            "analysis_summary": analysis_summary,
            "analysis_text": analysis_text,
            "latest_experiment_id": latest.get("experiment_id"),
            "latest_metrics": latest.get("metrics", {}),
            "latest_logs_path": latest.get("logs_path", ""),
        }
        analysis_json_path = save_text_artifact(
            state,
            f"results/analysis_iteration_{iteration}.json",
            json.dumps(analysis_payload, ensure_ascii=False, indent=2),
        )

        debug_update: dict[str, Any] = {}
        if not meets_target:
            debug_info = state.get("debug_info", {})
            loop_count = int(debug_info.get("loop_count", 0)) + 1
            max_loops = int(debug_info.get("max_loops", 3))
            debug_update = {
                "debug_info": {
                    "loop_count": loop_count,
                    "max_loops": max_loops,
                    "error_analysis": (
                        f"Target not met (target={target_accuracy}, "
                        f"best_accuracy={best_metrics.get('accuracy', 0)})."
                    ),
                    "fix_suggestion": _extract_improvement_suggestion(analysis_text),
                    "discussion_points": discussion_points,
                    "missing_checks": missing_checks,
                },
            }

        handoff_payload = {
            "iteration": iteration,
            "execution_success": bool(latest.get("success", False)),
            "needs_rework": not meets_target,
            "feedback_for_coder": _extract_improvement_suggestion(analysis_text),
            "discussion_points": discussion_points,
            "missing_checks": missing_checks,
            "analysis_json_path": analysis_json_path,
            "artifact_paths": [analysis_json_path, latest.get("logs_path", "")],
            "decision": "TARGET_MET" if meets_target else "NEEDS_IMPROVEMENT",
        }
        handoff_path = persist_handoff_state(state, handoff_payload, logger=logger)

        if logger:
            logger.log_agent_message(
                agent_name,
                (
                    f"Decision: {'TARGET_MET' if meets_target else 'NEEDS_IMPROVEMENT'} / "
                    f"best_accuracy={best_metrics.get('accuracy', 'N/A')} / "
                    f"analysis_json={analysis_json_path}"
                ),
            )

        return {
            **update_phase(state, "analysis_complete"),
            "analysis": analysis_summary,
            "meets_target": meets_target,
            "best_metrics": best_metrics,
            "latest_analysis_json_path": analysis_json_path,
            "handoff_state_path": handoff_path,
            **debug_update,
        }

    return analyzer_node


def _check_target_met(analysis: str, results: list, target_accuracy: float) -> bool:
    upper = analysis.upper()
    if "DECISION: TARGET_MET" in upper or "TARGET_MET" in upper:
        return True
    if results:
        latest = results[-1]
        metrics = latest.get("metrics", {})
        accuracy = metrics.get("accuracy", 0)
        if isinstance(accuracy, (int, float)) and float(accuracy) >= target_accuracy:
            return True
    return False


def _get_best_metrics(results: list) -> dict:
    if not results:
        return {}
    best = {}
    best_accuracy = -1.0
    for result in results:
        metrics = result.get("metrics", {})
        accuracy = metrics.get("accuracy", 0)
        if isinstance(accuracy, (int, float)) and float(accuracy) > best_accuracy:
            best_accuracy = float(accuracy)
            best = metrics.copy()
    return best


def _extract_improvement_suggestion(analysis: str) -> str:
    lines = [line.strip() for line in analysis.splitlines() if line.strip()]
    collected: list[str] = []
    capture = False
    for line in lines:
        lowered = line.lower()
        if any(token in lowered for token in ["needs_improvement", "next step", "fix", "improvement"]):
            capture = True
        if capture:
            collected.append(line)
            if len(collected) >= 8:
                break
    text = "\n".join(collected).strip()
    return text[:1000] if text else "Revise model/training setup and rerun with focused diagnostics."


def _extract_bullets(text: str, keywords: list[str]) -> list[str]:
    bullets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        has_keyword = any(keyword in lowered for keyword in keywords)
        is_bullet = bool(re.match(r"^([-*]|\d+\.)\s+", line))
        if has_keyword and (is_bullet or len(line) < 240):
            cleaned = re.sub(r"^([-*]|\d+\.)\s+", "", line).strip()
            if cleaned:
                bullets.append(cleaned)
        if len(bullets) >= 10:
            break
    return bullets


def _summarize_analysis(text: str, max_lines: int = 10) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "No analysis generated."
    return "\n".join(lines[:max_lines])[:1200]
