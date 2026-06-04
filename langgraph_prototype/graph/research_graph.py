"""
Research workflow graph definition.

Flow:
    START -> planner -> designer -> coder -> executor
                                 -> analyzer -> (writer | coder | failure)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import ResearchState


def _latest_execution_success(state: ResearchState) -> bool:
    results = state.get("experiment_results", [])
    if not results:
        return False
    return bool(results[-1].get("success", False))


def should_continue_or_debug(state: ResearchState) -> str:
    """Route after analyzer."""

    debug_info = state.get("debug_info", {})
    loop_count = int(debug_info.get("loop_count", 0))
    max_loops = int(debug_info.get("max_loops", 3))

    if state.get("meets_target", False) and _latest_execution_success(state):
        return "writer"

    if loop_count >= max_loops:
        return "failure"

    return "coder"


def _route_after_coding(state: ResearchState) -> str:
    """coder 후 라우팅: executor | coder(자기 루프 repair)"""
    code_status = state.get("code_status", "not_started")
    if code_status == "complete":
        return "executor"
    debug_info = state.get("debug_info", {})
    repair_count = debug_info.get("repair_count", 0)
    if repair_count >= 3:
        return "executor"
    return "coder"


def check_execution_result(state: ResearchState) -> str:
    """Route after executor."""

    debug_info = state.get("debug_info", {})
    loop_count = int(debug_info.get("loop_count", 0))
    max_loops = int(debug_info.get("max_loops", 3))

    if state.get("latest_execution_success"):
        return "analyzer"

    if loop_count >= max_loops:
        return "failure"

    if state.get("code_status") == "incomplete":
        return "coder"

    return "analyzer"


def build_research_graph() -> StateGraph:
    """Return an unbound state graph shell."""

    return StateGraph(ResearchState)


def create_compiled_graph(
    planner_fn,
    designer_fn,
    coder_fn,
    executor_fn,
    analyzer_fn,
    writer_fn,
    failure_fn,
):
    """Bind node callables and compile graph."""

    graph = StateGraph(ResearchState)

    graph.add_node("planner", planner_fn)
    graph.add_node("designer", designer_fn)
    graph.add_node("coder", coder_fn)
    graph.add_node("executor", executor_fn)
    graph.add_node("analyzer", analyzer_fn)
    graph.add_node("writer", writer_fn)
    graph.add_node("failure", failure_fn)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "designer")
    graph.add_edge("designer", "coder")
    # [Fix] 직접 엣지 제거 → 조건부 엣지로 교체 (code_status 기반 repair 루프)
    graph.add_conditional_edges(
        "coder",
        _route_after_coding,
        {"executor": "executor", "coder": "coder"},
    )

    graph.add_conditional_edges(
        "executor",
        check_execution_result,
        {
            "analyzer": "analyzer",
            "coder": "coder",
            "failure": "failure",
        },
    )

    graph.add_conditional_edges(
        "analyzer",
        should_continue_or_debug,
        {
            "writer": "writer",
            "coder": "coder",
            "failure": "failure",
        },
    )

    graph.add_edge("writer", END)
    graph.add_edge("failure", END)

    return graph.compile()


def get_graph_visualization_mermaid() -> str:
    """Mermaid view for docs."""

    return """
graph TD
    START([START]) --> planner[Research Planner]
    planner --> designer[Experiment Designer]
    designer --> coder[Code Generator]
    coder --> executor[Experiment Executor]

    executor -->|success| analyzer[Result Analyzer]
    executor -->|failed & retry left| coder
    executor -->|failed & retry exhausted| failure[Failure Handler]

    analyzer -->|target met| writer[Paper Writer]
    analyzer -->|needs rework| coder
    analyzer -->|retry exhausted| failure

    writer --> END([END])
    failure --> END
"""
