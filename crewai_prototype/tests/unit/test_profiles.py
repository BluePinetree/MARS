from __future__ import annotations

from profiles import (
    GenericScriptProfile,
    TabularSupervisedProfile,
    TimeseriesForecastingProfile,
    VisionClassificationProfile,
    select_research_profile,
)


def test_select_research_profile_preserves_v1_selection_semantics():
    assert isinstance(select_research_profile({"research_profile": "vision"}), VisionClassificationProfile)
    assert isinstance(select_research_profile({"profile": "tabular_supervised"}), TabularSupervisedProfile)
    assert isinstance(select_research_profile({"constraints": {"profile": "timeseries"}}), TimeseriesForecastingProfile)
    assert isinstance(
        select_research_profile({"research_topic": "Forecasting demand with rolling window backtests"}),
        TimeseriesForecastingProfile,
    )
    assert isinstance(
        select_research_profile({"research_goal": "Image classification on CIFAR-100"}),
        VisionClassificationProfile,
    )
    assert isinstance(
        select_research_profile({"research_domain": "structured data regression on CSV features"}),
        TabularSupervisedProfile,
    )
    assert isinstance(select_research_profile({"research_topic": "generic experiment"}), GenericScriptProfile)


def test_profile_selection_keeps_primary_metric_for_vision_topics():
    profile = select_research_profile(
        {
            "research_topic": "CIFAR-100 image classification baseline",
            "research_goal": "compare a ResNet and a ViT",
            "research_domain": "vision",
        }
    )

    assert isinstance(profile, VisionClassificationProfile)
    assert profile.primary_metric == "accuracy"
    assert profile.runtime_required_inputs() == ("data_root",)


def test_profile_metadata_describes_real_scaffold_contracts():
    vision = VisionClassificationProfile()
    generic = GenericScriptProfile()
    tabular = TabularSupervisedProfile()
    timeseries = TimeseriesForecastingProfile()

    assert vision.scaffold_type == "vision_classification"
    assert "src/data.py" in vision.mutable_scaffold_files()
    assert vision.scaffold_metadata()["supports_real_execution"] is True
    assert generic.scaffold_type == "generic_python_experiment"
    assert generic.runtime_required_inputs() == ("script_path",)
    assert "script_path" in generic.scaffold_metadata()["required_runtime_inputs"]
    assert tabular.runtime_required_inputs() == ("data_path", "target_column")
    assert timeseries.runtime_required_inputs() == ("data_path", "timestamp_column", "target_column")


def test_generic_profile_projects_runtime_metrics_over_script_scores():
    generic = GenericScriptProfile()

    extracted = generic.extract_metrics_from_payload(
        {
            "execution_success": True,
            "report_ready_hint": True,
            "quality_gate_status": "passed",
            "metrics": {"accuracy": 0.93, "score": 0.93},
            "experiments": [
                {
                    "requested_script_path": "C:/tmp/smoke.py",
                    "canonicalized_requested_script_path": "C:/tmp/smoke.py",
                    "executed_script_path": "C:/tmp/smoke.py",
                    "canonicalized_executed_script_path": "C:/tmp/smoke.py",
                    "script_path_exact_match": True,
                }
            ],
        }
    )

    assert extracted["metrics"]["script_execution_success_fraction"] == 1.0
    assert extracted["metrics"]["artifact_contract_pass_fraction"] == 1.0
    assert extracted["metrics"]["requested_script_path_match_fraction"] == 1.0
    assert extracted["metrics"]["script_reported_metrics"]["accuracy"] == 0.93
    assert extracted["metrics"]["primary_metric_name"] == "requested_script_path_match_fraction"
