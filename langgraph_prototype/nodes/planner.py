"""Research Planner node — Anthropic SDK 직접 사용."""

from __future__ import annotations

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

try:
    from tools.pinecone_tool import get_last_pinecone_query_diagnostics
except Exception:
    def get_last_pinecone_query_diagnostics():
        return {}


PLANNER_SYSTEM_PROMPT = """You are the Research Planner.

Create a rigorous plan with:
1) problem framing and motivation
2) related work summary
3) testable hypotheses
4) step-by-step experiment plan
5) risks and fallback strategies
6) concrete success criteria

Return structured markdown.
"""


def create_planner_node(client, model: str, logger=None, literature_tool=None):
    def planner_node(state: ResearchState) -> dict:
        agent_name = "Research Planner"

        topic = str(state.get("research_input", {}).get("research_topic", "N/A"))
        if logger:
            logger.log_agent_thinking(agent_name, f"Planning research for topic: {topic}")

        literature_context = ""
        if literature_tool:
            try:
                if logger:
                    logger.log_tool_call(agent_name, "pinecone_search", {"query": topic})
                search_results = literature_tool.search(topic)
                literature_context = f"\n\n## Retrieved Literature\n{search_results}"
                query_diag = get_last_pinecone_query_diagnostics()
                if query_diag.get("status") == "failure":
                    if logger:
                        logger.log_agent_message("System", f"Pinecone search failed: {query_diag}")
                elif logger:
                    logger.log_tool_result(agent_name, "Literature search completed.", success=True)
            except Exception as exc:
                if logger:
                    logger.log_tool_result(agent_name, f"Literature search failed: {exc}", success=False)
                literature_context = "\n\n(No external retrieval available. Use model priors.)"

        research_context = get_research_context(state, agent_name=agent_name, logger=logger)
        user_prompt = (
            f"{research_context}{literature_context}\n\n"
            "Build a concrete research plan for the requested objective."
        )

        t0 = time.time()
        response = with_retry(
            client.messages.create,
            model=model,
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=2048,
        )
        plan = response.content[0].text

        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="planner",
                    phase="exit",
                    tokens_in=response.usage.input_tokens,
                    tokens_out=response.usage.output_tokens,
                    duration_ms=(time.time() - t0) * 1000,
                ))
            except Exception:
                pass

        if logger:
            logger.log_agent_message(agent_name, "Planning complete. Routing to designer.")
            logger.log_phase_complete(1, "Research Planning")

        return {
            **update_phase(state, "planning_complete"),
            "plan": plan,
            "literature_review": literature_context if literature_context else "No retrieval context.",
        }

    return planner_node
