from __future__ import annotations

from typing import Any, Dict, Optional

from profiles.base import BaseResearchProfile


class TimeseriesForecastingProfile(BaseResearchProfile):
    name = "timeseries_forecasting"
    description = "Single-series or grouped time-series forecasting profile with forecast/backtest metrics."
    primary_metric = "rmse"
    scaffold_type = "timeseries_forecasting"

    def mutable_scaffold_files(self):
        return super().mutable_scaffold_files() + (
            "src/dataset.py",
            "src/features.py",
            "src/models.py",
            "src/forecast.py",
            "src/backtest.py",
        )

    def runtime_required_inputs(self):
        return ("data_path", "timestamp_column", "target_column")

    def runtime_contract_notes(self):
        return (
            "The scaffold expects timestamp_column, target_column, horizon, and window_size.",
            "Irregular-frequency handling must be explicit and should fail when the requested policy cannot be applied.",
            "Benchmark/reportable runs should use a real backtest path rather than a synthetic shortcut.",
        )

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

        candidates = {
            "rmse": pick("rmse", "backtest_rmse"),
            "mae": pick("mae", "backtest_mae"),
            "mape": pick("mape", "backtest_mape"),
            "smape": pick("smape", "backtest_smape"),
            "r2": pick("r2", "backtest_r2"),
        }
        for name, value in candidates.items():
            if value is None:
                continue
            metrics[name] = value
            metrics_unit[name] = "raw" if name != "r2" else "score"

        primary_name = "rmse" if metrics.get("rmse") is not None else ("mae" if metrics.get("mae") is not None else "mape")
        primary_value = metrics.get(primary_name)
        if primary_value is not None:
            metrics["primary_metric_name"] = primary_name
            metrics["primary_metric_value"] = primary_value
            metrics_unit["primary_metric_name"] = "label"
            metrics_unit["primary_metric_value"] = metrics_unit.get(primary_name, "raw")

        horizon = payload.get("horizon")
        window_size = payload.get("window_size")
        if horizon is not None:
            metrics["horizon"] = horizon
            metrics_unit["horizon"] = "steps"
        if window_size is not None:
            metrics["window_size"] = window_size
            metrics_unit["window_size"] = "steps"

        return {
            "metrics": metrics,
            "metrics_unit": metrics_unit,
            "normalized_metrics": normalized,
        }
