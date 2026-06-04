from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple


class BaseResearchProfile:
    """Base profile for domain-specific parsing and validation defaults."""

    name = "generic_script"
    description = "Generic single-entry Python experiment profile."
    primary_metric = "accuracy"
    scaffold_type = "generic_python_experiment"
    supports_real_execution = True
    prefer_runtime_metric_projection = False

    def stable_scaffold_files(self) -> Tuple[str, ...]:
        return (
            "src/main.py",
            "src/cli.py",
            "src/config_schema.py",
            "src/artifacts.py",
        )

    def mutable_scaffold_files(self) -> Tuple[str, ...]:
        return (
            "src/experiment_impl.py",
            "src/experiment_registry.py",
            "src/result_reducer.py",
            "src/validation.py",
        )

    def runtime_required_inputs(self) -> Tuple[str, ...]:
        return ()

    def runtime_contract_notes(self) -> Tuple[str, ...]:
        return (
            "Missing required runtime inputs must raise ValueError instead of returning fake success.",
        )

    def scaffold_metadata(self, scaffold_type: Optional[str] = None) -> Dict[str, Any]:
        resolved_scaffold_type = str(scaffold_type or self.scaffold_type).strip()
        return {
            "profile_name": self.name,
            "profile_description": self.description,
            "scaffold_type": resolved_scaffold_type,
            "primary_metric": self.primary_metric,
            "supports_real_execution": bool(self.supports_real_execution),
            "required_runtime_inputs": list(self.runtime_required_inputs()),
            "stable_files": list(self.stable_scaffold_files()),
            "mutable_files": list(self.mutable_scaffold_files()),
            "runtime_contract_notes": list(self.runtime_contract_notes()),
        }

    @staticmethod
    def _lookup_nested(data: Dict[str, Any], path: Sequence[str]) -> Any:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            text = str(value).strip()
            if not text:
                return None
            return float(text)
        except (TypeError, ValueError):
            return None

    def _top1_fraction_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("best_test_top1_fraction",),
            ("last_test_top1_fraction",),
            ("test", "top1_fraction"),
            ("metrics", "accuracy_fraction"),
            ("metrics", "test_top1_fraction"),
            ("metrics", "test_top1_best_fraction_mean"),
            ("metrics", "test_top1_last_fraction_mean"),
            ("accuracy_fraction",),
            ("test_top1_fraction",),
        )

    def _top1_percent_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("best_test_top1_percent",),
            ("last_test_top1_percent",),
            ("test", "top1_percent"),
            ("metrics", "accuracy_percent"),
            ("metrics", "test_top1_percent"),
            ("metrics", "test_top1_best_percent_mean"),
            ("metrics", "test_top1_last_percent_mean"),
            ("accuracy_percent",),
            ("test_top1_percent",),
        )

    def _accuracy_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("accuracy",),
            ("metrics", "accuracy"),
            ("metrics", "test_top1"),
        )

    def _test_top1_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("metrics", "test_top1"),
            ("metrics", "test_top1_fraction"),
            ("metrics", "test_top1_best_fraction_mean"),
            ("metrics", "test_top1_last_fraction_mean"),
            ("test_top1",),
            ("test_top1_fraction",),
        )

    def _test_top5_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("metrics", "test_top5"),
            ("metrics", "test_top5_fraction"),
            ("test_top5",),
            ("test_top5_fraction",),
        )

    def _best_val_top1_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("metrics", "best_val_top1"),
            ("metrics", "best_val_top1_fraction"),
            ("best_val_top1",),
            ("best_val_top1_fraction",),
        )

    def _test_loss_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("metrics", "test_loss"),
            ("test_loss",),
        )

    def _nested_fraction_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("best", "test_top1_fraction"),
            ("final", "test_top1_fraction"),
            ("test_top1_best_fraction_mean",),
            ("test_top1_last_fraction_mean",),
            ("test_top1_fraction",),
            ("accuracy_fraction",),
        )

    def _nested_percent_paths(self) -> Tuple[Tuple[str, ...], ...]:
        return (
            ("best", "test_top1_percent"),
            ("final", "test_top1_percent"),
            ("test_top1_best_percent_mean",),
            ("test_top1_last_percent_mean",),
            ("test_top1_percent",),
            ("accuracy_percent",),
        )

    def extract_metrics_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        metrics_unit = payload.get("metrics_unit") if isinstance(payload.get("metrics_unit"), dict) else {}
        normalized = payload.get("normalized_metrics") if isinstance(payload.get("normalized_metrics"), dict) else {}
        metrics_blob = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}

        nested_experiment_metrics: Dict[str, Any] = {}
        nested_best_experiment = ""
        nested_best_fraction: Optional[float] = None
        nested_best_percent: Optional[float] = None
        for exp_key, exp_payload in metrics_blob.items():
            if not isinstance(exp_payload, dict):
                continue

            candidate_fraction = None
            for candidate in self._nested_fraction_paths():
                candidate_fraction = self._coerce_float(self._lookup_nested(exp_payload, candidate))
                if candidate_fraction is not None:
                    break

            candidate_percent = None
            for candidate in self._nested_percent_paths():
                candidate_percent = self._coerce_float(self._lookup_nested(exp_payload, candidate))
                if candidate_percent is not None:
                    break

            if candidate_fraction is None and candidate_percent is not None:
                candidate_fraction = candidate_percent / 100.0 if candidate_percent > 1.0 else candidate_percent
            if candidate_percent is None and candidate_fraction is not None:
                candidate_percent = candidate_fraction * 100.0

            if candidate_fraction is None and candidate_percent is None:
                continue

            nested_experiment_metrics[str(exp_key)] = exp_payload
            if nested_best_fraction is None or candidate_fraction > nested_best_fraction:
                nested_best_experiment = str(exp_key)
                nested_best_fraction = candidate_fraction
                nested_best_percent = candidate_percent

        top1_fraction = None
        for candidate in self._top1_fraction_paths():
            top1_fraction = self._coerce_float(self._lookup_nested(payload, candidate))
            if top1_fraction is not None:
                break
        if top1_fraction is None:
            for candidate_key in (
                "accuracy_fraction",
                "test_top1_fraction",
                "best_val_top1_fraction",
            ):
                top1_fraction = self._coerce_float(normalized.get(candidate_key))
                if top1_fraction is not None:
                    break

        top1_percent = None
        for candidate in self._top1_percent_paths():
            top1_percent = self._coerce_float(self._lookup_nested(payload, candidate))
            if top1_percent is not None:
                break
        if top1_percent is None and top1_fraction is not None:
            top1_percent = top1_fraction * 100.0

        accuracy = None
        for candidate in self._accuracy_paths():
            accuracy = self._coerce_float(self._lookup_nested(payload, candidate))
            if accuracy is not None:
                break

        test_top1 = None
        for candidate in self._test_top1_paths():
            test_top1 = self._coerce_float(self._lookup_nested(payload, candidate))
            if test_top1 is not None:
                break

        test_top5 = None
        for candidate in self._test_top5_paths():
            test_top5 = self._coerce_float(self._lookup_nested(payload, candidate))
            if test_top5 is not None:
                break

        best_val_top1 = None
        for candidate in self._best_val_top1_paths():
            best_val_top1 = self._coerce_float(self._lookup_nested(payload, candidate))
            if best_val_top1 is not None:
                break

        test_loss = None
        for candidate in self._test_loss_paths():
            test_loss = self._coerce_float(self._lookup_nested(payload, candidate))
            if test_loss is not None:
                break

        if top1_fraction is None and nested_best_fraction is not None:
            top1_fraction = nested_best_fraction
        if top1_percent is None and nested_best_percent is not None:
            top1_percent = nested_best_percent
        if top1_fraction is None and test_top1 is not None:
            top1_fraction = test_top1
        if top1_percent is None:
            top1_percent = self._coerce_float(normalized.get("test_top1_percent"))
            if top1_percent is None and top1_fraction is not None:
                top1_percent = top1_fraction * 100.0
        if accuracy is None and test_top1 is not None:
            accuracy = test_top1

        if nested_experiment_metrics:
            metrics["experiments"] = nested_experiment_metrics
            if nested_best_experiment:
                metrics["best_experiment"] = nested_best_experiment

        if top1_fraction is not None:
            metrics["accuracy"] = top1_fraction
            metrics_unit = {**metrics_unit, "accuracy": "fraction"}
            normalized = {
                **normalized,
                "accuracy_fraction": top1_fraction,
                "accuracy_percent": top1_percent if top1_percent is not None else float(top1_fraction) * 100.0,
            }
        elif accuracy is not None:
            metrics["accuracy"] = accuracy
            if "accuracy" not in metrics_unit:
                metrics_unit = {**metrics_unit, "accuracy": "fraction"}
            if "accuracy_fraction" not in normalized:
                normalized = {
                    **normalized,
                    "accuracy_fraction": float(accuracy),
                    "accuracy_percent": float(accuracy) * 100.0,
                }

        if test_top1 is not None:
            metrics["test_top1"] = test_top1
            metrics_unit = {**metrics_unit, "test_top1": "fraction"}
            normalized = {
                **normalized,
                "test_top1_fraction": test_top1,
                "test_top1_percent": self._coerce_float(normalized.get("test_top1_percent"))
                if self._coerce_float(normalized.get("test_top1_percent")) is not None
                else test_top1 * 100.0,
            }
        if test_top5 is not None:
            metrics["test_top5"] = test_top5
            metrics_unit = {**metrics_unit, "test_top5": "fraction"}
            normalized = {
                **normalized,
                "test_top5_fraction": test_top5,
                "test_top5_percent": self._coerce_float(normalized.get("test_top5_percent"))
                if self._coerce_float(normalized.get("test_top5_percent")) is not None
                else test_top5 * 100.0,
            }
        if best_val_top1 is not None:
            metrics["best_val_top1"] = best_val_top1
            metrics_unit = {**metrics_unit, "best_val_top1": "fraction"}
            normalized = {
                **normalized,
                "best_val_top1_fraction": best_val_top1,
                "best_val_top1_percent": self._coerce_float(normalized.get("best_val_top1_percent"))
                if self._coerce_float(normalized.get("best_val_top1_percent")) is not None
                else best_val_top1 * 100.0,
            }
        if test_loss is not None:
            metrics["test_loss"] = test_loss
            metrics_unit = {**metrics_unit, "test_loss": "nats"}

        return {
            "metrics": metrics,
            "metrics_unit": metrics_unit,
            "normalized_metrics": normalized,
        }
