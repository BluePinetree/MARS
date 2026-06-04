from __future__ import annotations

import json
from pathlib import Path

from core.project_manifest import ProjectFileSpec, ProjectManifest
from core.run_contract import CliArgSpec, RunContract
from scaffolds.builder import ScaffoldBuilder
from scaffolds.registry import select_scaffold_type


def test_project_manifest_roundtrip_preserves_shape() -> None:
    manifest = ProjectManifest(
        scaffold_type="vision_classification",
        description="vision scaffold",
        entrypoint="src/main.py",
        mutable_files=["src/experiment_impl.py"],
        files=[ProjectFileSpec("src/main.py", "entrypoint", ["main"], mutable=False)],
        metadata={"profile_name": "vision_classification"},
    )

    payload = manifest.to_dict()
    restored = ProjectManifest.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.files[0].required_symbols == ["main"]


def test_run_contract_roundtrip_preserves_shape() -> None:
    contract = RunContract(
        scaffold_type="tabular_supervised",
        entrypoint="src/main.py",
        mutable_module="src/experiment_impl.py",
        cli_args=[CliArgSpec("--exp_id", "selector", aliases=["--exp-id"])],
        required_symbols={"src/main.py": ["main"]},
        required_artifacts=["results/result.json"],
        result_json_schema={"required_top_level_keys": ["execution_success"]},
        validation_metadata_schema={"validation_tier": ["smoke", "failed"]},
        notes=["stable"],
    )

    payload = contract.to_dict()
    restored = RunContract.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.cli_args[0].aliases == ["--exp-id"]


def test_scaffold_builder_materializes_workspace(tmp_path) -> None:
    builder = ScaffoldBuilder(
        output_root=tmp_path / "run_1",
        research_input={
            "scaffold_type": "timeseries_forecasting",
            "research_topic": "forecasting demand",
            "research_domain": "time series",
        },
        profile_name="timeseries_forecasting",
    )

    materialization = builder.materialize()

    assert materialization.workspace_root.exists()
    assert materialization.entrypoint_path.exists()
    assert materialization.mutable_module_path.exists()
    assert materialization.manifest_path.exists()
    assert materialization.run_contract_path.exists()
    assert (materialization.workspace_root / "src" / "dataset.py").exists()
    assert (materialization.workspace_root / "src" / "backtest.py").exists()

    manifest = ProjectManifest.from_dict(json.loads(materialization.manifest_path.read_text(encoding="utf-8")))
    contract = RunContract.from_dict(json.loads(materialization.run_contract_path.read_text(encoding="utf-8")))

    assert manifest.scaffold_type == "timeseries_forecasting"
    assert contract.mutable_module == "src/experiment_impl.py"
    assert select_scaffold_type("timeseries_forecasting", {"research_topic": "forecasting demand"}) == "timeseries_forecasting"


def test_vision_scaffold_uses_executable_modules_not_placeholders(tmp_path) -> None:
    builder = ScaffoldBuilder(
        output_root=tmp_path / "vision_run",
        research_input={
            "scaffold_type": "vision_classification",
            "research_topic": "CIFAR-100 image classification",
            "research_domain": "vision",
        },
        profile_name="vision_classification",
    )

    materialization = builder.materialize()

    data_py = (materialization.workspace_root / "src" / "data.py").read_text(encoding="utf-8")
    model_py = (materialization.workspace_root / "src" / "models.py").read_text(encoding="utf-8")
    train_py = (materialization.workspace_root / "src" / "train.py").read_text(encoding="utf-8")
    eval_py = (materialization.workspace_root / "src" / "evaluate.py").read_text(encoding="utf-8")

    assert "Reserved scaffold module" not in data_py
    assert "load_image_dataset" in data_py
    assert "datasets.CIFAR100" in data_py
    assert "download=True" in data_py
    assert "build_image_model" in model_py
    assert "train_image_model" in train_py
    assert "evaluate_image_model" in eval_py


def test_generic_scaffold_generates_executable_script_runner(tmp_path) -> None:
    builder = ScaffoldBuilder(
        output_root=tmp_path / "generic_run",
        research_input={
            "scaffold_type": "generic_python_experiment",
            "research_topic": "single script smoke test",
            "research_domain": "generic",
        },
        profile_name="generic_script",
    )

    materialization = builder.materialize()
    experiment_impl = (materialization.workspace_root / "src" / "experiment_impl.py").read_text(encoding="utf-8")
    experiment_registry = (materialization.workspace_root / "src" / "experiment_registry.py").read_text(encoding="utf-8")
    config_schema = (materialization.workspace_root / "src" / "config_schema.py").read_text(encoding="utf-8")

    assert "NotImplementedError" not in experiment_impl
    assert "subprocess.run" in experiment_impl
    assert "script_path" in experiment_impl
    assert "requested_script_path" in experiment_impl
    assert "script_path_exact_match" in experiment_impl
    assert '"script_path": script_path' in experiment_registry
    assert "script_path: str = \"\"" in config_schema


def test_select_scaffold_type_prefers_explicit_profile_name():
    assert select_scaffold_type("Automation/QA engineer", {"profile": "generic_script"}) == "generic_python_experiment"
