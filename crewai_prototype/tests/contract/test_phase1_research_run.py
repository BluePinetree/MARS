"""Contract tests for real V2 runs without runtime mocks in active code paths."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from textwrap import dedent

import httpx

from api.app import create_app
from entrypoints.init import initialize_runtime


async def _request(app, method: str, path: str, json_payload: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=json_payload)


def _wait_for_terminal_status(app, run_id: str, *, timeout_seconds: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict | None = None
    while time.monotonic() < deadline:
        response = asyncio.run(_request(app, "GET", f"/api/v1/research/{run_id}/status"))
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Run did not reach a terminal state within {timeout_seconds} seconds: {last_payload}")


def _write_generic_script(tmp_path: Path) -> Path:
    script_path = tmp_path / "bin" / "generic_success.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        dedent(
            """
            from __future__ import annotations

            import json
            import os
            from pathlib import Path

            results_root = Path(os.environ["RESEARCH_RESULTS_ROOT"])
            results_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "success": True,
                "execution_success": True,
                "dataset_origin": "real",
                "evaluation_scope": "full_test",
                "validation_tier": "reportable",
                "accuracy": 0.91,
                "test_top1": 0.91,
                "metrics": {
                    "score": 0.91,
                    "accuracy_fraction": 0.91,
                },
                "notes": ["generic script executed successfully"],
            }
            (results_root / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return script_path


def _install_fake_structured_generation(monkeypatch, *, force_retry_once: bool = False) -> None:
    from runtime import structured_generation

    analyzer_calls = {"count": 0}

    def _fake_generate(*, schema_name: str, prompt: str, output_schema, required_keys=None, **kwargs):
        if schema_name == "planner_output":
            return {
                "problem_statement": "Execute a user-supplied Python script and validate its result artifact.",
                "research_questions": ["Can the supplied script produce a valid result artifact?"],
                "hypotheses": ["A valid script can complete end-to-end through the V2 runtime."],
                "success_criteria": ["Persist a machine-readable result artifact.", "Preserve session and artifact metadata."],
                "constraints": ["No runtime fallback is allowed."],
                "risks": [{"risk": "The script may not write result.json.", "mitigation": "Fail execution explicitly."}],
                "deliverables": ["planning.json", "design.json", "report.md"],
                "recommended_profile": "generic_script",
                "next_stage_inputs": {
                    "primary_metric": "score",
                    "evaluation_focus": "generic script execution",
                },
            }
        if schema_name == "designer_output":
            return {
                "experiment_family": "generic script execution",
                "dataset_strategy": {"source": "script output", "split_plan": ["N/A for generic script execution"]},
                "baseline_plan": ["Run the supplied script exactly once and validate results/result.json."],
                "experiment_matrix": [{"id": "exp_baseline", "focus": "script_run", "expected_signal": "A valid result artifact is produced."}],
                "evaluation_protocol": {"primary_metric": "score", "secondary_metrics": ["runtime", "artifact_integrity"]},
                "artifact_plan": ["Persist results/result.json", "Persist execution summary", "Persist report.md"],
                "implementation_handoff": {"entrypoint_expectation": "Use the materialized scaffold baseline.", "next_stage": "coder"},
                "scaffold_type": "generic_python_experiment",
            }
        if schema_name == "analyzer_output":
            analyzer_calls["count"] += 1
            if force_retry_once and analyzer_calls["count"] == 1:
                return {
                    "analysis_decision": {
                        "run_id": "",
                        "iteration": 1,
                        "execution_success": True,
                        "needs_rework": True,
                        "ready_for_report": False,
                        "decision_reason": "Exercise a real repair loop before reporting.",
                        "fix_instructions": [
                            "Update derive_validation_outcome in src/validation.py to keep reportability checks explicit."
                        ],
                        "risk_flags": ["retry_requested_for_contract_test"],
                        "next_stage": "coder",
                    },
                    "repair_actions": [
                        {
                            "action_type": "tighten_quality_gate",
                            "path": "src/validation.py",
                            "operation": "replace_function",
                            "symbol": "derive_validation_outcome",
                            "reason": "Keep reportability checks explicit across iterations.",
                            "metadata": {"quality_gate_mode": "strict_contract"},
                        }
                    ],
                    "evidence": ["Execution produced a valid result artifact."],
                    "report_readiness": ["One repair pass is requested before writing."],
                }
            return {
                "analysis_decision": {
                    "run_id": "",
                    "iteration": analyzer_calls["count"],
                    "execution_success": True,
                    "needs_rework": False,
                    "ready_for_report": True,
                    "decision_reason": "Execution produced a valid result artifact with real metrics.",
                    "fix_instructions": [],
                    "risk_flags": [],
                    "next_stage": "writer",
                },
                "repair_actions": [],
                "evidence": ["Execution produced a valid result artifact."],
                "report_readiness": ["The run is ready for report generation."],
            }
        if schema_name == "writer_output":
            return {
                "title": "Research Report: Generic Script Execution",
                "executive_summary": "The supplied script executed and produced a valid result artifact.",
                "planning_summary": "The run selected the generic script profile.",
                "design_summary": "The design used the materialized scaffold baseline.",
                "execution_summary": "Execution succeeded through the local subprocess backend.",
                "analysis_summary": "The analyzer marked the run ready for report generation.",
                "next_steps": ["Inspect the generated report and artifacts."],
                "report_markdown": "# Research Report\n\nThe generic script execution completed successfully.\n",
            }
        raise AssertionError(f"Unexpected schema_name: {schema_name}")

    monkeypatch.setattr(structured_generation, "generate_structured_json", _fake_generate)


def test_phase4_research_run_executes_generic_script_baseline(tmp_path, monkeypatch):
    _install_fake_structured_generation(monkeypatch)
    services = initialize_runtime(project_root=tmp_path)
    app = create_app(services)
    script_path = _write_generic_script(tmp_path)

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/api/v1/research",
            {
                "topic": "Run an external Python script through the real V2 runtime",
                "goal": "Verify that the scaffold baseline executes without coder fallbacks",
                "domain": "generic automation",
                "profile": "generic_script",
                "script_path": str(script_path),
                "working_dir": str(tmp_path),
                "dataset_origin": "real",
                "evaluation_scope": "full_test",
                "validation_tier": "reportable",
            },
        )
    )
    assert response.status_code == 200
    response_payload = response.json()
    run_id = response_payload["run_id"]
    assert response_payload["status"] in {"queued", "running"}

    status_payload = _wait_for_terminal_status(app, run_id)
    assert status_payload["status"] == "completed"
    assert status_payload["progress"] == 100

    result_response = asyncio.run(_request(app, "GET", f"/api/v1/research/{run_id}/result"))
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["status"] == "completed"

    artifact_labels = {artifact["label"] for artifact in result_payload["artifacts"]}
    assert {
        "planning.json",
        "design.json",
        "coding_iteration_1.json",
        "execution_iteration_1.json",
        "analysis_iteration_1.json",
        "writing_iteration_1.json",
        "result.json",
        "report.md",
        "project_manifest.json",
        "run_contract.json",
        "workspace_validation.json",
    } <= artifact_labels

    output_path = Path(result_payload["output_path"])
    execution_payload = json.loads((output_path / "results" / "execution_iteration_1.json").read_text(encoding="utf-8"))
    coding_payload = json.loads((output_path / "results" / "coding_iteration_1.json").read_text(encoding="utf-8"))
    result_payload_artifact = json.loads((output_path / "results" / "result.json").read_text(encoding="utf-8"))
    assert coding_payload["patch_plan"]["strategy"] == "use_materialized_scaffold"
    assert coding_payload["generated_targets"] == []
    assert coding_payload["patch_application"]["blocked"] is False
    assert execution_payload["execution_success"] is True
    assert execution_payload["result_payload"]["execution_backend"] == "local_subprocess"
    assert execution_payload["result_artifact"]["dataset_origin"] == "real"
    assert execution_payload["result_artifact"]["experiments"][0]["metrics"]["score"] == 0.91
    assert result_payload_artifact["status"] == "success"


def test_phase4_research_run_retries_once_before_reporting(tmp_path, monkeypatch):
    _install_fake_structured_generation(monkeypatch, force_retry_once=True)
    services = initialize_runtime(project_root=tmp_path)
    app = create_app(services)
    script_path = _write_generic_script(tmp_path)

    response = asyncio.run(
        _request(
            app,
            "POST",
            "/api/v1/research",
            {
                "topic": "Exercise one repair loop with a real generic scaffold",
                "goal": "Verify that repair iterations no longer rely on a canned experiment_impl replacement",
                "domain": "generic automation",
                "profile": "generic_script",
                "script_path": str(script_path),
                "working_dir": str(tmp_path),
                "dataset_origin": "real",
                "evaluation_scope": "full_test",
                "validation_tier": "reportable",
                "max_fix_iterations": 2,
            },
        )
    )
    assert response.status_code == 200
    response_payload = response.json()
    run_id = response_payload["run_id"]
    assert response_payload["status"] in {"queued", "running"}

    status_payload = _wait_for_terminal_status(app, run_id)
    assert status_payload["status"] == "completed"

    result_response = asyncio.run(_request(app, "GET", f"/api/v1/research/{run_id}/result"))
    assert result_response.status_code == 200
    result_payload = result_response.json()
    output_path = Path(result_payload["output_path"])

    repair_handoff = json.loads((output_path / "results" / "repair_handoff_iteration_1.json").read_text(encoding="utf-8"))
    coding_iteration_1 = json.loads((output_path / "results" / "coding_iteration_1.json").read_text(encoding="utf-8"))
    coding_iteration_2 = json.loads((output_path / "results" / "coding_iteration_2.json").read_text(encoding="utf-8"))
    analysis_iteration_1 = json.loads((output_path / "results" / "analysis_iteration_1.json").read_text(encoding="utf-8"))
    analysis_iteration_2 = json.loads((output_path / "results" / "analysis_iteration_2.json").read_text(encoding="utf-8"))

    assert coding_iteration_1["patch_plan"]["strategy"] == "use_materialized_scaffold"
    assert analysis_iteration_1["analysis_decision"]["needs_rework"] is True
    assert repair_handoff["repair_actions"][0]["path"] == "src/validation.py"
    assert coding_iteration_2["selected_patch_operations"] == ["replace_function"]
    assert coding_iteration_2["patch_application"]["blocked"] is False
    assert analysis_iteration_2["analysis_decision"]["ready_for_report"] is True
