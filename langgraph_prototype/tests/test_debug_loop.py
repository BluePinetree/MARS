"""
Debug-loop integration tests for the LangGraph prototype.
"""

from graph.research_graph import create_compiled_graph
from graph.state import ExperimentResult, ResearchInput, create_initial_state
from nodes.base import update_phase


def test_debug_loop_then_success():
    call_count = {"coder": 0, "executor": 0, "analyzer": 0}

    def dummy_planner(state):
        return {**update_phase(state, "planner_complete"), "plan": "test plan"}

    def dummy_designer(state):
        return {**update_phase(state, "designer_complete"), "design": "test design"}

    def dummy_coder(state):
        call_count["coder"] += 1
        return {**update_phase(state, "coding_complete"), "code": f"# code v{call_count['coder']}"}

    def dummy_executor(state):
        call_count["executor"] += 1
        if call_count["executor"] == 1:
            accuracy = 0.75
        else:
            accuracy = 0.95
        result = ExperimentResult(
            experiment_id=f"exp_{call_count['executor']}",
            metrics={"accuracy": accuracy},
            success=True,
        )
        return {
            **update_phase(state, "execution_complete"),
            "experiment_results": [result],
            "current_experiment_id": result["experiment_id"],
        }

    def dummy_analyzer(state):
        call_count["analyzer"] += 1
        latest = state.get("experiment_results", [])[-1]
        accuracy = latest.get("metrics", {}).get("accuracy", 0)
        if accuracy >= 0.90:
            return {
                **update_phase(state, "analysis_complete"),
                "analysis": "target met",
                "meets_target": True,
                "best_metrics": {"accuracy": accuracy},
            }
        debug_info = state.get("debug_info", {})
        return {
            **update_phase(state, "analysis_complete"),
            "analysis": "needs improvement",
            "meets_target": False,
            "best_metrics": {"accuracy": accuracy},
            "debug_info": {
                "loop_count": int(debug_info.get("loop_count", 0)) + 1,
                "max_loops": int(debug_info.get("max_loops", 3)),
                "error_analysis": f"accuracy {accuracy} < 0.90",
                "fix_suggestion": "tune training config",
                "discussion_points": ["underfitting signs"],
                "missing_checks": ["seed stability"],
            },
        }

    def dummy_writer(state):
        return {
            **update_phase(state, "writing_complete"),
            "report": "final report",
            "report_path": "/tmp/report.md",
            "status": "completed",
        }

    def dummy_failure(state):
        return {
            **update_phase(state, "failed"),
            "status": "failed",
            "error": "should not fail",
        }

    graph = create_compiled_graph(
        planner_fn=dummy_planner,
        designer_fn=dummy_designer,
        coder_fn=dummy_coder,
        executor_fn=dummy_executor,
        analyzer_fn=dummy_analyzer,
        writer_fn=dummy_writer,
        failure_fn=dummy_failure,
    )

    inp = ResearchInput(
        research_topic="debug loop test",
        research_goal="validate retry then success",
        research_domain="testing",
        output_path="/tmp/test",
    )
    final = graph.invoke(create_initial_state(inp, "test_session", "test_run", max_loops=3))

    assert final["status"] == "completed"
    assert final["meets_target"] is True
    assert call_count["coder"] == 2
    assert call_count["executor"] == 2
    assert call_count["analyzer"] == 2
    assert len(final["experiment_results"]) == 2


def test_debug_loop_max_exceeded_to_failure():
    call_count = {"coder": 0, "executor": 0, "analyzer": 0}

    def dummy_planner(state):
        return {**update_phase(state, "planner_complete"), "plan": "plan"}

    def dummy_designer(state):
        return {**update_phase(state, "designer_complete"), "design": "design"}

    def dummy_coder(state):
        call_count["coder"] += 1
        return {**update_phase(state, "coding_complete"), "code": f"# v{call_count['coder']}"}

    def dummy_executor(state):
        call_count["executor"] += 1
        result = ExperimentResult(
            experiment_id=f"exp_{call_count['executor']}",
            metrics={"accuracy": 0.50},
            success=True,
        )
        return {
            **update_phase(state, "execution_complete"),
            "experiment_results": [result],
            "current_experiment_id": result["experiment_id"],
        }

    def dummy_analyzer(state):
        call_count["analyzer"] += 1
        debug_info = state.get("debug_info", {})
        loop_count = int(debug_info.get("loop_count", 0)) + 1
        return {
            **update_phase(state, "analysis_complete"),
            "analysis": "still below target",
            "meets_target": False,
            "best_metrics": {"accuracy": 0.50},
            "debug_info": {
                "loop_count": loop_count,
                "max_loops": int(debug_info.get("max_loops", 3)),
                "error_analysis": "accuracy 0.50 < 0.90",
                "fix_suggestion": "rework architecture",
                "discussion_points": ["performance plateau"],
                "missing_checks": ["data normalization audit"],
            },
        }

    def dummy_writer(state):
        return {
            **update_phase(state, "writing_complete"),
            "report": "should not write",
            "report_path": "/tmp/report.md",
            "status": "completed",
        }

    def dummy_failure(state):
        return {
            **update_phase(state, "failed"),
            "status": "failed",
            "error": "retry budget exhausted",
        }

    graph = create_compiled_graph(
        planner_fn=dummy_planner,
        designer_fn=dummy_designer,
        coder_fn=dummy_coder,
        executor_fn=dummy_executor,
        analyzer_fn=dummy_analyzer,
        writer_fn=dummy_writer,
        failure_fn=dummy_failure,
    )

    inp = ResearchInput(
        research_topic="max loop test",
        research_goal="must stop with failure",
        research_domain="testing",
        output_path="/tmp/test",
    )
    final = graph.invoke(create_initial_state(inp, "test_session", "test_run", max_loops=3))

    assert final["status"] == "failed"
    assert final["meets_target"] is False
    assert call_count["coder"] >= 3
    assert call_count["executor"] >= 3
    assert call_count["analyzer"] >= 3


def test_execution_failure_retry_then_success():
    call_count = {"coder": 0, "executor": 0}

    def dummy_planner(state):
        return {**update_phase(state, "planner_complete"), "plan": "plan"}

    def dummy_designer(state):
        return {**update_phase(state, "designer_complete"), "design": "design"}

    def dummy_coder(state):
        call_count["coder"] += 1
        return {**update_phase(state, "coding_complete"), "code": f"# v{call_count['coder']}"}

    def dummy_executor(state):
        call_count["executor"] += 1
        if call_count["executor"] == 1:
            debug_info = state.get("debug_info", {})
            failed = ExperimentResult(
                experiment_id="exp_fail",
                metrics={},
                success=False,
                error_message="SyntaxError: invalid syntax",
            )
            return {
                **update_phase(state, "execution_failed"),
                "experiment_results": [failed],
                "current_experiment_id": failed["experiment_id"],
                "debug_info": {
                    "loop_count": int(debug_info.get("loop_count", 0)) + 1,
                    "max_loops": int(debug_info.get("max_loops", 3)),
                    "error_analysis": "syntax error",
                    "fix_suggestion": "fix invalid syntax",
                    "discussion_points": [],
                    "missing_checks": [],
                },
            }

        passed = ExperimentResult(
            experiment_id="exp_success",
            metrics={"accuracy": 0.92},
            success=True,
        )
        return {
            **update_phase(state, "execution_complete"),
            "experiment_results": [passed],
            "current_experiment_id": passed["experiment_id"],
        }

    def dummy_analyzer(state):
        return {
            **update_phase(state, "analysis_complete"),
            "analysis": "target met",
            "meets_target": True,
            "best_metrics": {"accuracy": 0.92},
        }

    def dummy_writer(state):
        return {
            **update_phase(state, "writing_complete"),
            "report": "report",
            "report_path": "/tmp/report.md",
            "status": "completed",
        }

    def dummy_failure(state):
        return {
            **update_phase(state, "failed"),
            "status": "failed",
            "error": "should not fail",
        }

    graph = create_compiled_graph(
        planner_fn=dummy_planner,
        designer_fn=dummy_designer,
        coder_fn=dummy_coder,
        executor_fn=dummy_executor,
        analyzer_fn=dummy_analyzer,
        writer_fn=dummy_writer,
        failure_fn=dummy_failure,
    )

    inp = ResearchInput(
        research_topic="execution failure test",
        research_goal="recover after first failure",
        research_domain="testing",
        output_path="/tmp/test",
    )
    final = graph.invoke(create_initial_state(inp, "test_session", "test_run", max_loops=3))

    assert final["status"] == "completed"
    assert call_count["coder"] == 2
    assert call_count["executor"] == 2
