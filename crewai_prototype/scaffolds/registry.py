from __future__ import annotations

from typing import Any, Dict


PROFILE_TO_SCAFFOLD = {
    "generic_script": "generic_python_experiment",
    "generic_python_experiment": "generic_python_experiment",
    "vision_classification": "vision_classification",
    "tabular_supervised": "tabular_supervised",
    "timeseries_forecasting": "timeseries_forecasting",
}


def _normalize_profile_name(value: Any) -> str:
    return PROFILE_TO_SCAFFOLD.get(str(value or "").strip().lower(), "")


def select_scaffold_type(profile_name: str, research_input: Dict[str, Any]) -> str:
    explicit = str(
        research_input.get("scaffold_type")
        or research_input.get("workspace_scaffold")
        or research_input.get("constraints", {}).get("scaffold_type", "")
    ).strip().lower()
    if explicit in {"vision_classification", "generic_python_experiment", "tabular_supervised", "timeseries_forecasting"}:
        return explicit
    requested_profile = _normalize_profile_name(
        research_input.get("profile") or research_input.get("profile_name") or profile_name
    )
    if requested_profile:
        return requested_profile
    joined = " ".join(
        str(x or "")
        for x in (
            research_input.get("research_topic"),
            research_input.get("research_goal"),
            research_input.get("research_domain"),
            research_input.get("data_description"),
        )
    ).lower()
    if any(
        marker in joined
        for marker in (
            "time series",
            "timeseries",
            "forecasting",
            "forecast",
            "backtest",
            "temporal",
            "lag feature",
            "rolling window",
            "horizon",
            "smape",
        )
    ):
        return "timeseries_forecasting"
    if any(
        marker in joined
        for marker in (
            "tabular",
            "structured data",
            "structured dataset",
            "csv",
            "spreadsheet",
            "feature engineering",
            "xgboost",
            "lightgbm",
            "catboost",
            "random forest",
        )
    ):
        return "tabular_supervised"
    return "generic_python_experiment"
