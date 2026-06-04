"""Research input normalization helpers for the V2 coordinator."""

from __future__ import annotations

from typing import Any


class ResearchInputNormalizer:
    """Normalize coordinator inputs and resolve loop/profile defaults."""

    @staticmethod
    def normalize(research_input: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(research_input)
        if "research_topic" not in normalized and normalized.get("topic"):
            normalized["research_topic"] = normalized["topic"]
        if "research_goal" not in normalized and normalized.get("goal"):
            normalized["research_goal"] = normalized["goal"]
        if "research_domain" not in normalized and normalized.get("domain"):
            normalized["research_domain"] = normalized["domain"]
        if "topic" not in normalized and normalized.get("research_topic"):
            normalized["topic"] = normalized["research_topic"]
        if "goal" not in normalized and normalized.get("research_goal"):
            normalized["goal"] = normalized["research_goal"]
        if "domain" not in normalized and normalized.get("research_domain"):
            normalized["domain"] = normalized["research_domain"]
        if "data_root" not in normalized and normalized.get("data_path"):
            normalized["data_root"] = normalized["data_path"]
        topic_text = " ".join(
            str(normalized.get(key, "") or "")
            for key in ("research_topic", "topic", "research_goal", "goal", "research_domain", "domain", "data_description")
        ).lower()
        if "data_root" not in normalized and ("cifar100" in topic_text or "cifar-100" in topic_text):
            # Two levels up from outputs/run_*/ → crewai_prototype/.cache/cifar100
            normalized["data_root"] = "../../.cache/cifar100"
            normalized.setdefault("download", True)
            normalized.setdefault("dataset_origin", "real")
            normalized.setdefault("evaluation_scope", "full_test")
            normalized.setdefault("epochs", 1)
            normalized.setdefault("num_workers", 0)
        return normalized

    @staticmethod
    def resolve_profile_name(research_input: dict[str, Any], planning_output: dict[str, Any]) -> str:
        for key in ("profile", "profile_name"):
            explicit = str(research_input.get(key) or "").strip().lower()
            if explicit:
                return explicit
        recommended = str(planning_output.get("recommended_profile") or "").strip().lower()
        if recommended in {"generic_script", "generic_python_experiment", "vision_classification", "tabular_supervised", "timeseries_forecasting"}:
            return recommended
        return "generic_script"

    @staticmethod
    def resolve_max_fix_iterations(research_input: dict[str, Any]) -> int:
        raw_value = research_input.get("max_fix_iterations", research_input.get("max_iterations", 3))
        try:
            return max(1, int(raw_value))
        except (TypeError, ValueError):
            return 3
