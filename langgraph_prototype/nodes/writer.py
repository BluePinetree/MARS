"""Paper Writer node — Anthropic SDK 직접 사용."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

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
from nodes.base import get_research_context, update_phase


WRITER_SYSTEM_PROMPT = """You are the Paper Writer.

Write a final research report with:
- abstract
- introduction
- related work
- methodology
- results
- discussion
- conclusion
- appendix with reproducibility details

Use markdown and be precise.
"""


def create_writer_node(client, model: str, logger=None, settings=None):
    def writer_node(state: ResearchState) -> dict:
        agent_name = "Paper Writer"

        if logger:
            logger.log_agent_thinking(agent_name, "Composing final report from all artifacts.")

        research_context = get_research_context(state, agent_name=agent_name, logger=logger)
        analysis_summary = str(state.get("analysis", ""))
        best_metrics = state.get("best_metrics", {})
        latest_analysis_json_path = state.get("latest_analysis_json_path", "")
        experiment_summary = _build_experiment_summary(state.get("experiment_results", []))

        user_prompt = (
            f"{research_context}\n\n"
            f"## Analysis Summary\n{analysis_summary}\n\n"
            f"## Best Metrics\n{best_metrics}\n\n"
            f"## Latest Analysis JSON Path\n{latest_analysis_json_path}\n\n"
            f"## Experiment History\n{experiment_summary}\n\n"
            "Write the final report with clear evidence and reproducibility details."
        )

        t0 = time.time()
        response = with_retry(
            client.messages.create,
            model=model,
            system=WRITER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=4096,
        )
        report = response.content[0].text

        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="writer",
                    phase="exit",
                    tokens_in=response.usage.input_tokens,
                    tokens_out=response.usage.output_tokens,
                    duration_ms=(time.time() - t0) * 1000,
                ))
            except Exception:
                pass

        report_path = _save_report(state, report)

        if logger:
            logger.log_file_created(agent_name, report_path)
            logger.log_agent_message(agent_name, f"Final report generated: {report_path}")
            logger.log_phase_complete(6, "Paper Writing")

        return {
            **update_phase(state, "writing_complete"),
            "report": report,
            "report_path": report_path,
            "status": "completed",
        }

    return writer_node


def _build_experiment_summary(results: list) -> str:
    if not results:
        return "No experiment results available."

    lines: list[str] = []
    for index, item in enumerate(results, 1):
        lines.append(f"### Experiment {index}")
        lines.append(f"- id: {item.get('experiment_id', 'N/A')}")
        lines.append(f"- success: {item.get('success', False)}")
        lines.append(f"- metrics: {item.get('metrics', {})}")
        lines.append(f"- logs_path: {item.get('logs_path', '')}")
        if item.get("error_message"):
            lines.append(f"- error: {item.get('error_message')}")
        if item.get("wandb_run_url"):
            lines.append(f"- wandb: {item.get('wandb_run_url')}")
        lines.append("")

    return "\n".join(lines)


def _save_report(state: ResearchState, report: str) -> str:
    research_input = state.get("research_input", {})
    output_path = str(research_input.get("output_path", "./outputs"))
    run_id = str(state.get("run_id", "unknown"))

    run_dir = Path(output_path) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    report_path = run_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")

    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    metrics_payload = {
        "best_metrics": state.get("best_metrics", {}),
        "all_experiments": [
            {
                "experiment_id": item.get("experiment_id"),
                "success": item.get("success"),
                "metrics": item.get("metrics", {}),
                "logs_path": item.get("logs_path", ""),
            }
            for item in state.get("experiment_results", [])
        ],
        "latest_analysis_json_path": state.get("latest_analysis_json_path", ""),
    }
    (results_dir / "metrics.json").write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return str(report_path.resolve())
