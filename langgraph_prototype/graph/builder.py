"""Graph builder — Anthropic SDK 클라이언트 주입."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from config.llm_factory import create_anthropic_client, get_agent_model
from config.settings import Settings, load_settings
from graph.research_graph import create_compiled_graph
from nodes.analyzer import create_analyzer_node
from nodes.coder import create_coder_node
from nodes.designer import create_designer_node
from nodes.executor import create_executor_node
from nodes.failure import create_failure_node
from nodes.planner import create_planner_node
from nodes.writer import create_writer_node

# rsp/ telemetry (optional)
_RSP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_RSP_ROOT))

try:
    from rsp.telemetry import TelemetryStore
    _TELEMETRY_AVAILABLE = True
except Exception:
    _TELEMETRY_AVAILABLE = False


def build_graph(
    settings: Optional[Settings] = None,
    workspace_root: Optional[str] = None,
    logger=None,
    pinecone_tool=None,
    docker_tool=None,
    wandb_tool=None,
):
    """Build and compile the full research graph."""

    if settings is None:
        settings = load_settings()

    client = create_anthropic_client()
    model = get_agent_model(settings, "default") or "claude-sonnet-4-6"

    # TelemetryStore 초기화
    if _TELEMETRY_AVAILABLE and workspace_root:
        telemetry_log = os.path.join(workspace_root, "logs", "telemetry.jsonl")
        try:
            TelemetryStore.init(telemetry_log)
        except Exception:
            pass

    planner_fn = create_planner_node(
        client=client,
        model=get_agent_model(settings, "planner"),
        logger=logger,
        literature_tool=pinecone_tool,
    )
    designer_fn = create_designer_node(
        client=client,
        model=get_agent_model(settings, "designer"),
        logger=logger,
        methodology_tool=pinecone_tool,
    )
    coder_fn = create_coder_node(
        client=client,
        model=get_agent_model(settings, "coder"),
        is_repair=False,
    )
    executor_fn = create_executor_node(
        client=client,
        model=get_agent_model(settings, "executor"),
    )
    analyzer_fn = create_analyzer_node(
        client=client,
        model=get_agent_model(settings, "analyzer"),
        logger=logger,
        wandb_tool=wandb_tool,
        settings=settings,
    )
    writer_fn = create_writer_node(
        client=client,
        model=get_agent_model(settings, "writer"),
        logger=logger,
        settings=settings,
    )
    failure_fn = create_failure_node(logger=logger)

    compiled_graph = create_compiled_graph(
        planner_fn=planner_fn,
        designer_fn=designer_fn,
        coder_fn=coder_fn,
        executor_fn=executor_fn,
        analyzer_fn=analyzer_fn,
        writer_fn=writer_fn,
        failure_fn=failure_fn,
    )

    if logger:
        logger.log_agent_message(
            "System",
            "Graph built with nodes: planner/designer/coder/executor/analyzer/writer/failure",
        )

    return compiled_graph


def build_graph_dry_run(settings: Optional[Settings] = None):
    """Build graph with dummy nodes for structure checks."""

    def _dummy_node(name: str):
        def node_fn(state):
            from nodes.base import update_phase
            return {
                **update_phase(state, f"{name}_complete"),
                "status": "running",
            }
        return node_fn

    def _dummy_executor(state):
        from graph.state import ExperimentResult
        from nodes.base import update_phase
        result = {
            "experiment_id": "dry_run_exp",
            "metrics": {"accuracy": 0.95},
            "success": True,
            "error_message": "",
        }
        return {
            **update_phase(state, "execution_complete"),
            "experiment_results": [result],
            "latest_execution_success": True,
        }

    def _dummy_analyzer(state):
        from nodes.base import update_phase
        return {
            **update_phase(state, "analysis_complete"),
            "analysis": "[DRY RUN] analysis complete",
            "meets_target": True,
            "best_metrics": {"accuracy": 0.95},
        }

    def _dummy_writer(state):
        from nodes.base import update_phase
        return {
            **update_phase(state, "writing_complete"),
            "report": "[DRY RUN] report",
            "report_path": "/tmp/dry_run_report.md",
            "status": "completed",
        }

    def _dummy_failure(state):
        from nodes.base import update_phase
        return {
            **update_phase(state, "failed"),
            "status": "failed",
            "error": "[DRY RUN] failure",
        }

    return create_compiled_graph(
        planner_fn=_dummy_node("planner"),
        designer_fn=_dummy_node("designer"),
        coder_fn=_dummy_node("coder"),
        executor_fn=_dummy_executor,
        analyzer_fn=_dummy_analyzer,
        writer_fn=_dummy_writer,
        failure_fn=_dummy_failure,
    )
