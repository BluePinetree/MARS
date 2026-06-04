"""
Failure handler node.
"""

from __future__ import annotations

from graph.state import ResearchState
from nodes.base import update_phase


def create_failure_node(logger=None):
    """Create a terminal failure node used when retry budget is exhausted."""

    def failure_node(state: ResearchState) -> dict:
        debug_info = state.get("debug_info", {})
        results = state.get("experiment_results", [])
        latest_error = ""
        if results:
            latest_error = str(results[-1].get("error_message", "")).strip()

        error = latest_error or str(debug_info.get("error_analysis", "")).strip()
        if not error:
            error = "Retry budget exhausted before reaching a stable result."

        if logger:
            logger.log_agent_message(
                "Failure Handler",
                f"????? ?? ??: {error}",
            )

        return {
            **update_phase(state, "failed"),
            "status": "failed",
            "error": error,
        }

    return failure_node
