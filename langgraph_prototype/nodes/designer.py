"""Experiment Designer node — Anthropic SDK 직접 사용."""

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


DESIGNER_SYSTEM_PROMPT = """You are the Experiment Designer.

Using the plan, produce:
1) explicit hypotheses
2) full methodology (data/model/training/eval)
3) hyperparameter search strategy
4) baseline and comparison rules
5) coding instructions for the Code Generator

Return structured markdown.
"""


def create_designer_node(client, model: str, logger=None, methodology_tool=None):
    def designer_node(state: ResearchState) -> dict:
        agent_name = "Experiment Designer"

        if logger:
            logger.log_agent_thinking(agent_name, "Designing executable experiment methodology.")

        methodology_context = ""
        if methodology_tool:
            domain = str(state.get("research_input", {}).get("research_domain", ""))
            query = f"{domain} experiment methodology"
            try:
                if logger:
                    logger.log_tool_call(agent_name, "pinecone_search", {"query": query})
                search_results = methodology_tool.search(query)
                methodology_context = f"\n\n## Retrieved Methodology Context\n{search_results}"
                query_diag = get_last_pinecone_query_diagnostics()
                if query_diag.get("status") == "failure":
                    if logger:
                        logger.log_agent_message("System", f"Pinecone search failed: {query_diag}")
                elif logger:
                    logger.log_tool_result(agent_name, "Methodology search completed.", success=True)
            except Exception as exc:
                if logger:
                    logger.log_tool_result(agent_name, f"Methodology search failed: {exc}", success=False)

        research_context = get_research_context(state, agent_name=agent_name, logger=logger)
        user_prompt = (
            f"{research_context}{methodology_context}\n\n"
            "Produce a concrete experiment design that can be directly implemented in code."
        )

        t0 = time.time()
        response = with_retry(
            client.messages.create,
            model=model,
            system=DESIGNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=2048,
        )
        design = response.content[0].text

        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="designer",
                    phase="exit",
                    tokens_in=response.usage.input_tokens,
                    tokens_out=response.usage.output_tokens,
                    duration_ms=(time.time() - t0) * 1000,
                ))
            except Exception:
                pass

        hypothesis = _extract_section(design, "## 1", "## 2")
        methodology = _extract_section(design, "## 2", "## 3")

        if logger:
            logger.log_agent_message(agent_name, "Design complete. Routing to coder.")
            logger.log_phase_complete(2, "Experiment Design")

        return {
            **update_phase(state, "design_complete"),
            "design": design,
            "hypothesis": hypothesis,
            "methodology": methodology,
        }

    return designer_node


def _extract_section(text: str, start_header: str, end_header: str) -> str:
    lines = text.split("\n")
    capturing = False
    result: list[str] = []

    for line in lines:
        if start_header in line:
            capturing = True
            continue
        if end_header in line and capturing:
            break
        if capturing:
            result.append(line)

    extracted = "\n".join(result).strip()
    return extracted if extracted else text[:700]
