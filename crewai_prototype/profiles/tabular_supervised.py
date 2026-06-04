from __future__ import annotations

from typing import Any, Dict, Optional

from profiles.base import BaseResearchProfile


class TabularSupervisedProfile(BaseResearchProfile):
    name = "tabular_supervised"
    description = "Structured-data supervised learning profile for classification and regression."
    primary_metric = "task_dependent_score"
    scaffold_type = "tabular_supervised"

    def mutable_scaffold_files(self):
        return super().mutable_scaffold_files() + (
            "src/preprocess.py",
            "src/features.py",
            "src/models.py",
            "src/train.py",
            "src/evaluate.py",
        )

    def runtime_required_inputs(self):
        return ("data_path", "target_column")

    def runtime_contract_notes(self):
        return (
            "The dataset path must exist and contain a target column.",
            "The scaffold must fail explicitly for unsupported task_type values.",
            "The training/evaluation helpers should produce real metrics for classification or regression baselines.",
        )

    @staticmethod
    def _task_type(payload: Dict[str, Any]) -> str:
        candidates = (
            payload.get("task_type"),
            (payload.get("selection") or {}).get("task_type") if isinstance(payload.get("selection"), dict) else None,
            (payload.get("metrics") or {}).get("task_type") if isinstance(payload.get("metrics"), dict) else None,
        )
        for candidate in candidates:
            text = str(candidate or "").strip().lower()
            if text in {"classification", "regression"}:
                return text
        return "classification"

    def extract_metrics_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        base = super().extract_metrics_from_payload(payload)
        metrics = dict(base.get("metrics", {}) or {})
        metrics_unit = dict(base.get("metrics_unit", {}) or {})
        normalized = dict(base.get("normalized_metrics", {}) or {})
        metrics_blob = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}

        def pick(*names: str) -> Optional[float]:
            for name in names:
                value = self._coerce_float(metrics_blob.get(name))
                if value is None:
                    value = self._coerce_float(payload.get(name))
                if value is not None:
                    return value
            return None

        task_type = self._task_type(payload)
        metrics["task_type"] = task_type
        metrics_unit["task_type"] = "label"

        classification_candidates = {
            "accuracy": pick("accuracy", "test_accuracy"),
            "f1": pick("f1", "macro_f1", "f1_macro"),
            "roc_auc": pick("roc_auc", "auc", "roc_auc_ovr"),
            "pr_auc": pick("pr_auc", "average_precision"),
            "log_loss": pick("log_loss", "cross_entropy"),
        }
        regression_candidates = {
            "rmse": pick("rmse"),
            "mae": pick("mae"),
            "r2": pick("r2"),
            "mape": pick("mape"),
        }

        for name, value in classification_candidates.items():
            if value is None:
                continue
            metrics[name] = value
            if name == "log_loss":
                metrics_unit[name] = "nats"
            else:
                metrics_unit[name] = "fraction"
                normalized.setdefault(f"{name}_fraction", value)
                normalized.setdefault(f"{name}_percent", value * 100.0)

        for name, value in regression_candidates.items():
            if value is None:
                continue
            metrics[name] = value
            metrics_unit[name] = "raw"

        if task_type == "regression":
            if "accuracy" in metrics:
                metrics.pop("accuracy", None)
                metrics_unit.pop("accuracy", None)
            primary_name = "rmse" if metrics.get("rmse") is not None else ("mae" if metrics.get("mae") is not None else "r2")
            primary_value = metrics.get(primary_name)
        else:
            primary_name = "f1" if metrics.get("f1") is not None else ("roc_auc" if metrics.get("roc_auc") is not None else "accuracy")
            primary_value = metrics.get(primary_name)

        if primary_value is not None:
            metrics["primary_metric_name"] = primary_name
            metrics["primary_metric_value"] = primary_value
            metrics_unit["primary_metric_name"] = "label"
            metrics_unit["primary_metric_value"] = metrics_unit.get(primary_name, "raw")

        return {
            "metrics": metrics,
            "metrics_unit": metrics_unit,
            "normalized_metrics": normalized,
        }
