from __future__ import annotations

from typing import Any, Dict

from profiles.base import BaseResearchProfile


class GenericScriptProfile(BaseResearchProfile):
    name = "generic_script"
    description = "Executable single-script profile that runs a user-supplied Python entrypoint and validates its result artifact."
    primary_metric = "script_execution_success_fraction"
    scaffold_type = "generic_python_experiment"
    prefer_runtime_metric_projection = True

    def runtime_required_inputs(self):
        return ("script_path",)

    def runtime_contract_notes(self):
        return (
            "The script path must resolve to an executable Python file.",
            "The script must write results/result.json before exiting.",
            "If the script path is missing, the scaffold must fail explicitly.",
        )

    def extract_metrics_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        metrics_blob = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        experiments = payload.get("experiments") if isinstance(payload.get("experiments"), list) else []
        primary = experiments[0] if experiments and isinstance(experiments[0], dict) else {}

        requested_script_path = str(
            primary.get("requested_script_path")
            or payload.get("requested_script_path")
            or primary.get("script_path")
            or payload.get("script_path")
            or ""
        ).strip()
        canonicalized_requested_script_path = str(
            primary.get("canonicalized_requested_script_path")
            or payload.get("canonicalized_requested_script_path")
            or requested_script_path
        ).strip()
        executed_script_path = str(
            primary.get("executed_script_path")
            or payload.get("executed_script_path")
            or primary.get("script_path")
            or payload.get("script_path")
            or ""
        ).strip()
        canonicalized_executed_script_path = str(
            primary.get("canonicalized_executed_script_path")
            or payload.get("canonicalized_executed_script_path")
            or executed_script_path
        ).strip()

        exact_match = primary.get("script_path_exact_match")
        if exact_match is None:
            exact_match = payload.get("script_path_exact_match")
        if not isinstance(exact_match, bool) and canonicalized_requested_script_path and canonicalized_executed_script_path:
            exact_match = canonicalized_requested_script_path == canonicalized_executed_script_path

        execution_success = bool(payload.get("execution_success", False))
        quality_gate_status = str(payload.get("quality_gate_status", "")).strip().lower()
        report_ready_hint = bool(payload.get("report_ready_hint", False))

        metrics: Dict[str, Any] = {
            "script_execution_success_fraction": 1.0 if execution_success else 0.0,
            "artifact_contract_pass_fraction": 1.0 if (quality_gate_status == "passed" and report_ready_hint) else 0.0,
        }
        metrics_unit: Dict[str, Any] = {
            "script_execution_success_fraction": "fraction",
            "artifact_contract_pass_fraction": "fraction",
        }
        normalized_metrics: Dict[str, Any] = {
            "script_execution_success_fraction": metrics["script_execution_success_fraction"],
            "artifact_contract_pass_fraction": metrics["artifact_contract_pass_fraction"],
        }

        if isinstance(exact_match, bool):
            fraction = 1.0 if exact_match else 0.0
            metrics["requested_script_path_match_fraction"] = fraction
            metrics_unit["requested_script_path_match_fraction"] = "fraction"
            normalized_metrics["requested_script_path_match_fraction"] = fraction

        if requested_script_path:
            metrics["requested_script_path"] = requested_script_path
            metrics_unit["requested_script_path"] = "path"
        if canonicalized_requested_script_path:
            metrics["canonicalized_requested_script_path"] = canonicalized_requested_script_path
            metrics_unit["canonicalized_requested_script_path"] = "path"
        if executed_script_path:
            metrics["executed_script_path"] = executed_script_path
            metrics_unit["executed_script_path"] = "path"
        if canonicalized_executed_script_path:
            metrics["canonicalized_executed_script_path"] = canonicalized_executed_script_path
            metrics_unit["canonicalized_executed_script_path"] = "path"

        if metrics_blob:
            metrics["script_reported_metrics"] = metrics_blob
            metrics_unit["script_reported_metrics"] = "object"

        primary_metric_name = (
            "requested_script_path_match_fraction"
            if "requested_script_path_match_fraction" in metrics
            else "script_execution_success_fraction"
        )
        metrics["primary_metric_name"] = primary_metric_name
        metrics["primary_metric_value"] = metrics.get(primary_metric_name)
        metrics_unit["primary_metric_name"] = "label"
        metrics_unit["primary_metric_value"] = "fraction"

        return {
            "metrics": metrics,
            "metrics_unit": metrics_unit,
            "normalized_metrics": normalized_metrics,
        }
