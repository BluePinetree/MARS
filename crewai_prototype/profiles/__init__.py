from __future__ import annotations

from typing import Any, Dict

from profiles.base import BaseResearchProfile
from profiles.generic_script import GenericScriptProfile
from profiles.tabular_supervised import TabularSupervisedProfile
from profiles.timeseries_forecasting import TimeseriesForecastingProfile
from profiles.vision_classification import VisionClassificationProfile


def select_research_profile(research_input: Dict[str, Any]) -> BaseResearchProfile:
    constraints = research_input.get("constraints", {})
    constraints = constraints if isinstance(constraints, dict) else {}

    explicit = (
        research_input.get("research_profile")
        or research_input.get("profile")
        or constraints.get("research_profile")
        or constraints.get("profile")
    )
    explicit_text = str(explicit or "").strip().lower()
    if explicit_text in {"vision", "vision_classification", "image_classification"}:
        return VisionClassificationProfile()
    if explicit_text in {"tabular", "tabular_supervised", "structured_data", "structured"}:
        return TabularSupervisedProfile()
    if explicit_text in {"timeseries", "timeseries_forecasting", "forecasting", "time_series"}:
        return TimeseriesForecastingProfile()
    if explicit_text in {"generic", "generic_script", "default"}:
        return GenericScriptProfile()

    joined = " ".join(
        str(x or "")
        for x in (
            research_input.get("research_topic"),
            research_input.get("research_goal"),
            research_input.get("research_domain"),
        )
    ).lower()
    vision_markers = (
        "cifar",
        "imagenet",
        "image classification",
        "computer vision",
        "image dataset",
        "vision transformer",
        "resnet",
        "vit",
    )
    tabular_markers = (
        "tabular",
        "structured data",
        "structured dataset",
        "csv",
        "spreadsheet",
        "feature engineering",
        "lightgbm",
        "xgboost",
        "catboost",
        "random forest",
        "logistic regression",
        "regression on tabular",
        "classification on tabular",
    )
    timeseries_markers = (
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
        "wape",
    )
    if any(marker in joined for marker in vision_markers):
        return VisionClassificationProfile()
    if any(marker in joined for marker in timeseries_markers):
        return TimeseriesForecastingProfile()
    if any(marker in joined for marker in tabular_markers):
        return TabularSupervisedProfile()
    return GenericScriptProfile()


__all__ = [
    "BaseResearchProfile",
    "GenericScriptProfile",
    "TabularSupervisedProfile",
    "TimeseriesForecastingProfile",
    "VisionClassificationProfile",
    "select_research_profile",
]
