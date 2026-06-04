from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from core.project_manifest import ProjectFileSpec, ProjectManifest
from core.run_contract import CliArgSpec, RunContract
from scaffolds.base import ScaffoldMaterialization
from scaffolds.registry import select_scaffold_type
from profiles import select_research_profile


def _to_pretty_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


@dataclass
class ScaffoldBuilder:
    output_root: Path
    research_input: Dict[str, Any]
    profile_name: str

    def _resolve_profile_and_type(self):
        """Return (profile, scaffold_type) — shared by all phase methods."""
        profile = select_research_profile(self.research_input)
        scaffold_type = select_scaffold_type(self.profile_name, self.research_input)
        profile_scaffold_type = str(getattr(profile, "scaffold_type", "") or "").strip().lower()
        if profile_scaffold_type:
            scaffold_type = profile_scaffold_type
        return profile, scaffold_type

    def _make_materialization(self, scaffold_type: str) -> ScaffoldMaterialization:
        workspace_root = self.output_root / "workspace"
        src_root = workspace_root / "src"
        tests_root = workspace_root / "tests"
        logs_root = workspace_root / "logs"
        results_root = workspace_root / "results"
        reports_root = workspace_root / "reports"
        for path in (workspace_root, src_root, tests_root, logs_root, results_root, reports_root):
            path.mkdir(parents=True, exist_ok=True)
        return ScaffoldMaterialization(
            scaffold_type=scaffold_type,
            workspace_root=workspace_root,
            src_root=src_root,
            tests_root=tests_root,
            logs_root=logs_root,
            results_root=results_root,
            reports_root=reports_root,
            entrypoint_path=src_root / "main.py",
            mutable_module_path=src_root / "experiment_impl.py",
            manifest_path=workspace_root / "project_manifest.json",
            run_contract_path=workspace_root / "run_contract.json",
        )

    # ── Phase-split API (I-01) ──────────────────────────────────────────

    def create_directory_structure(self) -> ScaffoldMaterialization:
        """Phase 1a: create dirs only — no files written yet."""
        _, scaffold_type = self._resolve_profile_and_type()
        return self._make_materialization(scaffold_type)

    def render_stable_files(self, materialization: ScaffoldMaterialization) -> None:
        """Phase 1a: write stable contract files (cli.py, artifacts.py, …)."""
        profile, _ = self._resolve_profile_and_type()
        files = self._render_files(materialization, profile, workspace_structure=None)
        for relative_path, content in files.items():
            target = materialization.workspace_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def build_manifest_from_designer(
        self,
        materialization: ScaffoldMaterialization,
        workspace_structure: dict | None = None,
    ) -> tuple[ProjectManifest, RunContract]:
        """Phase 1c: build and write manifest + run_contract from Designer output."""
        profile, _ = self._resolve_profile_and_type()
        manifest = self._build_manifest(materialization, profile, workspace_structure)
        run_contract = self._build_run_contract(materialization, profile)
        materialization.manifest_path.write_text(_to_pretty_json(manifest.to_dict()), encoding="utf-8")
        materialization.run_contract_path.write_text(_to_pretty_json(run_contract.to_dict()), encoding="utf-8")
        return manifest, run_contract

    # ── Legacy all-in-one API (backward compat) ─────────────────────────

    def materialize(self, workspace_structure: dict | None = None) -> ScaffoldMaterialization:
        profile, scaffold_type = self._resolve_profile_and_type()
        materialization = self._make_materialization(scaffold_type)

        files = self._render_files(materialization, profile, workspace_structure)
        for relative_path, content in files.items():
            target = materialization.workspace_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        manifest = self._build_manifest(materialization, profile, workspace_structure)
        run_contract = self._build_run_contract(materialization, profile)
        materialization.manifest_path.write_text(_to_pretty_json(manifest.to_dict()), encoding="utf-8")
        materialization.run_contract_path.write_text(_to_pretty_json(run_contract.to_dict()), encoding="utf-8")
        return materialization

    def _render_files(self, materialization: ScaffoldMaterialization, profile, workspace_structure: dict | None = None) -> Dict[str, str]:
        scaffold_type = materialization.scaffold_type

        # Stable files only — mutable files are LLM-generated by workspace_file_generator
        files: Dict[str, str] = {
            "src/cli.py": self._render_cli_py(scaffold_type),
            "src/config_schema.py": self._render_config_schema_py(scaffold_type),
            "src/artifacts.py": self._render_artifacts_py(),
            "src/main.py": self._render_main_py(),
            "tests/test_contract_smoke.py": self._render_contract_smoke_test(),
            "tests/test_cli_contract.py": self._render_cli_contract_test(),
            "README.md": self._render_readme(scaffold_type, workspace_structure),
        }
        # metrics.py는 vision/generic scaffold에서 stable 파일로 제공한다.
        # evaluate.py / train.py 가 batch_topk_accuracies 를 import 하는데,
        # LLM 이 metrics.py 를 쓸 때 다른 함수명을 쓰는 사례가 반복되므로
        # scaffold 레벨에서 정규 구현체를 제공해 불일치를 원천 차단한다.
        if scaffold_type in ("vision_classification", "generic_python_experiment"):
            files["src/metrics.py"] = self._render_metrics_py()
        return files

    def _render_readme(self, scaffold_type: str, workspace_structure: dict | None) -> str:
        from scaffolds.file_responsibilities import SCAFFOLD_FILE_RESPONSIBILITIES as _SCAFFOLD_FILE_RESPONSIBILITIES
        research_topic = str(self.research_input.get("research_topic", "")).strip()
        lines = [
            "# Workspace Scaffold",
            f"- scaffold_type: `{scaffold_type}`",
            f"- research_topic: `{research_topic or 'unspecified'}`",
            "",
            "## Stable Files (do not modify)",
            "- `src/main.py`",
            "- `src/cli.py`",
            "- `src/config_schema.py`",
            "- `src/artifacts.py`",
            *(["- `src/metrics.py` — batch_topk_accuracies, AverageMeter (scaffold-provided, do NOT overwrite)"]
              if scaffold_type in ("vision_classification", "generic_python_experiment") else []),
            "",
            "## Mutable Files (LLM-generated)",
        ]
        if workspace_structure and workspace_structure.get("files"):
            for f in workspace_structure["files"]:
                path = f.get("path", "")
                responsibility = f.get("responsibility", "")
                lines.append(f"- `{path}` — {responsibility}")
        else:
            entries = _SCAFFOLD_FILE_RESPONSIBILITIES.get(scaffold_type) or _SCAFFOLD_FILE_RESPONSIBILITIES["_default"]
            for path, responsibility, _ in entries:
                lines.append(f"- `{path}` — {responsibility}")
        lines += ["", "Iterations: prefer the smallest helper-module patch that resolves the current blocker."]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _default_mutable_specs(scaffold_type: str) -> List[ProjectFileSpec]:
        from scaffolds.file_responsibilities import SCAFFOLD_FILE_RESPONSIBILITIES as _SCAFFOLD_FILE_RESPONSIBILITIES
        entries = _SCAFFOLD_FILE_RESPONSIBILITIES.get(scaffold_type) or _SCAFFOLD_FILE_RESPONSIBILITIES["_default"]
        return [
            ProjectFileSpec(path, responsibility, symbols, mutable=True)
            for path, responsibility, symbols in entries
        ]

    @staticmethod
    def _mutable_file_list(profile, scaffold_type: str) -> List[str]:
        if hasattr(profile, "mutable_scaffold_files"):
            return list(profile.mutable_scaffold_files())
        base = [
            "src/experiment_impl.py",
            "src/experiment_registry.py",
            "src/result_reducer.py",
            "src/validation.py",
        ]
        if scaffold_type == "tabular_supervised":
            base.extend(
                [
                    "src/preprocess.py",
                    "src/features.py",
                    "src/models.py",
                    "src/train.py",
                    "src/evaluate.py",
                ]
            )
        if scaffold_type == "timeseries_forecasting":
            base.extend(
                [
                    "src/dataset.py",
                    "src/features.py",
                    "src/models.py",
                    "src/forecast.py",
                    "src/backtest.py",
                ]
            )
        return base

    def _build_manifest(self, materialization: ScaffoldMaterialization, profile, workspace_structure: dict | None = None) -> ProjectManifest:
        stable_specs: List[ProjectFileSpec] = [
            ProjectFileSpec("src/main.py", "Stable entrypoint for orchestrator execution.", ["main"], mutable=False),
            ProjectFileSpec("src/cli.py", "Stable CLI contract for orchestrator flags.", ["build_parser", "parse_args"], mutable=False),
            ProjectFileSpec("src/config_schema.py", "Runtime context schema shared by entrypoint and experiment module.", ["RuntimeContext"], mutable=False),
            ProjectFileSpec("src/artifacts.py", "Stable result/artifact writer helpers.", ["write_result_json"], mutable=False),
            ProjectFileSpec("tests/test_contract_smoke.py", "Minimal contract smoke test.", mutable=False),
            ProjectFileSpec("tests/test_cli_contract.py", "CLI import/contract smoke test.", mutable=False),
        ]

        # Build mutable specs from Designer's workspace_structure if available
        if workspace_structure and workspace_structure.get("files"):
            mutable_specs = [
                ProjectFileSpec(
                    f.get("path", ""),
                    f.get("responsibility", ""),
                    list(f.get("symbols") or []),
                    mutable=True,
                )
                for f in workspace_structure["files"]
                if f.get("path") and not f.get("path", "").startswith("src/main")
            ]
            # Sort by generation_order if provided — coder must write files in dependency order
            gen_order = workspace_structure.get("generation_order") or []
            if gen_order:
                order_map = {path: i for i, path in enumerate(gen_order)}
                mutable_specs.sort(key=lambda s: order_map.get(s.path, len(gen_order)))
            # Defense: experiment_impl.py must always be present (scaffold entrypoint depends on it)
            existing_paths = {s.path for s in mutable_specs}
            if "src/experiment_impl.py" not in existing_paths:
                impl_spec = ProjectFileSpec(
                    "src/experiment_impl.py",
                    "Main experiment entry — exposes run_single_experiment and run_selected_experiments.",
                    ["run_single_experiment", "run_selected_experiments"],
                    mutable=True,
                )
                mutable_specs.insert(0, impl_spec)
        else:
            mutable_specs = self._default_mutable_specs(materialization.scaffold_type)

        files = stable_specs + mutable_specs
        mutable_files = [spec.path for spec in mutable_specs]
        return ProjectManifest(
            scaffold_type=materialization.scaffold_type,
            description=(
                "Run-specific scaffold generated before coding starts. "
                "Stable contract files are fixed; iterative coding should target the smallest mutable helper module that resolves the blocker."
            ),
            entrypoint="src/main.py",
            mutable_files=mutable_files,
            patch_only_after_bootstrap=True,
            files=files,
            metadata={
                "profile_name": self.profile_name,
                "research_topic": self.research_input.get("research_topic", ""),
                "research_goal": self.research_input.get("research_goal", ""),
                "profile_runtime_spec": profile.scaffold_metadata(materialization.scaffold_type),
            },
        )

    def _build_run_contract(self, materialization: ScaffoldMaterialization, profile) -> RunContract:
        cli_args = [
            CliArgSpec("--output_root", "Directory where runtime artifacts should be written.", required=False, aliases=["--out_root", "--output-path"]),
            CliArgSpec("--data_root", "Dataset root or cache directory.", required=False, aliases=["--data-root"]),
            CliArgSpec("--device", "Execution device such as cuda or cpu.", required=False),
            CliArgSpec("--epochs", "Primary epoch count for the selected run.", required=False, aliases=["--max_epochs"]),
            CliArgSpec("--batch_size", "Primary batch size.", required=False, aliases=["--batch-size"]),
            CliArgSpec("--num_workers", "Dataloader worker count.", required=False, aliases=["--num-workers"]),
            CliArgSpec("--run_all", "Run all registered experiments.", required=False, aliases=["--run-all"]),
            CliArgSpec("--exp_id", "Canonical experiment selector.", required=False, aliases=["--exp-id"]),
            CliArgSpec("--exp_name", "Alternative experiment selector.", required=False, aliases=["--exp-name"]),
            CliArgSpec("--validation_tier", "Validation tier metadata.", required=False, aliases=["--validation-tier"]),
            CliArgSpec("--dataset_origin", "Dataset origin metadata.", required=False, aliases=["--dataset-origin"]),
            CliArgSpec("--evaluation_scope", "Evaluation scope metadata.", required=False, aliases=["--evaluation-scope"]),
            CliArgSpec("--iteration", "Current orchestrator iteration index.", required=False),
            CliArgSpec("--attempt_id", "Current orchestrator attempt identifier.", required=False, aliases=["--attempt-id"]),
            CliArgSpec("--download", "Allow builtin dataset download.", required=False),
            CliArgSpec("--overwrite", "Allow overwriting output artifacts.", required=False),
        ]
        if materialization.scaffold_type == "generic_python_experiment":
            cli_args.extend(
                [
                    CliArgSpec("--script_path", "Python script path executed by the generic scaffold.", required=False, aliases=["--script-path"]),
                    CliArgSpec("--script_args", "Shell-style argument string forwarded to the script.", required=False, aliases=["--script-args"]),
                    CliArgSpec("--working_dir", "Working directory for generic script execution.", required=False, aliases=["--working-dir"]),
                ]
            )
        if materialization.scaffold_type == "tabular_supervised":
            cli_args.extend(
                [
                    CliArgSpec("--data_path", "Structured dataset path (csv/parquet).", required=False, aliases=["--data-path"]),
                    CliArgSpec("--target_column", "Target column name for supervised learning.", required=False, aliases=["--target-column"]),
                    CliArgSpec("--task_type", "Either classification or regression.", required=False, aliases=["--task-type"]),
                    CliArgSpec("--id_column", "Optional identifier column excluded from features.", required=False, aliases=["--id-column"]),
                    CliArgSpec("--test_size", "Test split fraction for tabular experiments.", required=False, aliases=["--test-size"]),
                    CliArgSpec("--valid_size", "Validation split fraction for tabular experiments.", required=False, aliases=["--valid-size"]),
                ]
            )
        if materialization.scaffold_type == "timeseries_forecasting":
            cli_args.extend(
                [
                    CliArgSpec("--data_path", "Time-series dataset path (csv/parquet).", required=False, aliases=["--data-path"]),
                    CliArgSpec("--timestamp_column", "Timestamp column name.", required=False, aliases=["--timestamp-column"]),
                    CliArgSpec("--target_column", "Target series column name.", required=False, aliases=["--target-column"]),
                    CliArgSpec("--id_column", "Optional entity/group identifier column.", required=False, aliases=["--id-column"]),
                    CliArgSpec("--horizon", "Forecast horizon in steps.", required=False),
                    CliArgSpec("--window_size", "Lag window size in steps.", required=False, aliases=["--window-size"]),
                    CliArgSpec("--test_size", "Test split fraction for chronological holdout.", required=False, aliases=["--test-size"]),
                    CliArgSpec("--valid_size", "Validation split fraction for chronological holdout.", required=False, aliases=["--valid-size"]),
                    CliArgSpec("--frequency_policy", "Irregular-frequency handling policy: strict, resample, or drop.", required=False, aliases=["--frequency-policy"]),
                    CliArgSpec("--resample_frequency", "Optional explicit pandas frequency string for regularization.", required=False, aliases=["--resample-frequency"]),
                    CliArgSpec("--fill_method", "Missing-target fill strategy after regularization: ffill, bfill, interpolate, zero, or drop.", required=False, aliases=["--fill-method"]),
                    CliArgSpec("--backtest_mode", "Backtest mode: simple_holdout or rolling_origin_refit.", required=False, aliases=["--backtest-mode"]),
                    CliArgSpec("--rolling_train_min_size", "Minimum history size before rolling-origin refit backtest starts.", required=False, aliases=["--rolling-train-min-size"]),
                    CliArgSpec("--rolling_step_size", "Step size for rolling-origin refit backtest.", required=False, aliases=["--rolling-step-size"]),
                ]
            )

        required_symbols = {
            "src/main.py": ["main"],
            "src/cli.py": ["build_parser", "parse_args"],
            "src/artifacts.py": ["write_result_json"],
            "src/experiment_impl.py": ["run_single_experiment", "run_selected_experiments"],
            "src/experiment_registry.py": ["normalize_experiment_selector", "build_experiment_definitions", "select_experiments"],
            "src/result_reducer.py": ["build_result_payload"],
            "src/validation.py": ["derive_validation_outcome"],
        }
        notes = [
            "The mutable implementation must expose run_selected_experiments(args, runtime_context).",
            "Stable scaffold files should not be regenerated during iterative repair.",
            "Prefer patching helper modules like result_reducer.py or validation.py instead of replacing the orchestration function wholesale.",
        ]
        notes.extend(list(profile.runtime_contract_notes()))
        if materialization.scaffold_type == "generic_python_experiment":
            notes.extend(
                [
                    "The script path must exist and return a real result.json artifact.",
                    "Missing script_path must fail explicitly.",
                ]
            )
        if materialization.scaffold_type == "tabular_supervised":
            required_symbols.update(
                {
                    "src/preprocess.py": ["load_tabular_frame", "split_features_and_target"],
                    "src/features.py": ["build_feature_matrices"],
                    "src/models.py": ["build_estimator"],
                    "src/train.py": ["fit_estimator"],
                    "src/evaluate.py": ["evaluate_estimator"],
                }
            )
            notes.extend(
                [
                    "Tabular scaffold expects task_type to be classification or regression.",
                    "Prefer patching preprocess/features/models/train/evaluate helpers before widening changes in experiment_impl.py.",
                ]
            )
        if materialization.scaffold_type == "timeseries_forecasting":
            required_symbols.update(
                {
                    "src/dataset.py": ["load_timeseries_frame"],
                    "src/features.py": ["build_forecasting_matrices"],
                    "src/models.py": ["build_forecaster"],
                    "src/forecast.py": ["fit_and_generate_forecast"],
                    "src/backtest.py": ["evaluate_backtest"],
                }
            )
            notes.extend(
                [
                    "Timeseries scaffold expects timestamp_column, target_column, horizon, and window_size.",
                    "Prefer patching dataset/features/models/forecast/backtest helpers before widening changes in experiment_impl.py.",
                    "Irregular-frequency handling is controlled by frequency_policy/resample_frequency/fill_method.",
                    "Benchmark/reportable runs should prefer backtest_mode=rolling_origin_refit.",
                ]
            )

        return RunContract(
            scaffold_type=materialization.scaffold_type,
            entrypoint="src/main.py",
            mutable_module="src/experiment_impl.py",
            cli_args=cli_args,
            required_symbols=required_symbols,
            required_artifacts=[
                "results/result.json",
            ],
            result_json_schema={
                "required_top_level_keys": [
                    "execution_success",
                    "validation_tier",
                    "dataset_origin",
                    "evaluation_scope",
                ]
            },
            validation_metadata_schema={
                "dataset_origin": ["real", "unknown"],
                "evaluation_scope": ["full_test", "subset", "unknown"],
                "validation_tier": ["smoke", "sanity", "benchmark", "reportable", "failed"],
            },
            notes=notes,
        )

    @staticmethod
    def _render_cli_py(scaffold_type: str) -> str:
        extra_args = ""
        if scaffold_type == "vision_classification":
            extra_args = '''
    parser.add_argument("--architectures", "--models", dest="architectures", default=None,
                        help="Comma-separated model names to compare, e.g. 'resnet18,vit_tiny'")
    parser.add_argument("--dataset_name", "--dataset", dest="dataset_name", default=None,
                        help="Dataset name, e.g. 'cifar10', 'cifar100', 'imagenet'")
    parser.add_argument("--pretrained", action="store_true", help="Use pretrained weights")
'''
        elif scaffold_type == "tabular_supervised":
            extra_args = '''
    parser.add_argument("--data_path", "--data-path", dest="data_path", default=None)
    parser.add_argument("--target_column", "--target-column", dest="target_column", default=None)
    parser.add_argument("--task_type", "--task-type", dest="task_type", default="classification")
    parser.add_argument("--id_column", "--id-column", dest="id_column", default=None)
    parser.add_argument("--test_size", "--test-size", dest="test_size", type=float, default=0.2)
    parser.add_argument("--valid_size", "--valid-size", dest="valid_size", type=float, default=0.1)
'''
        elif scaffold_type == "generic_python_experiment":
            extra_args = '''
    parser.add_argument("--script_path", "--script-path", dest="script_path", default=None)
    parser.add_argument("--script_args", "--script-args", dest="script_args", default="")
    parser.add_argument("--working_dir", "--working-dir", dest="working_dir", default=None)
'''
        elif scaffold_type == "timeseries_forecasting":
            extra_args = '''
    parser.add_argument("--data_path", "--data-path", dest="data_path", default=None)
    parser.add_argument("--timestamp_column", "--timestamp-column", dest="timestamp_column", default=None)
    parser.add_argument("--target_column", "--target-column", dest="target_column", default=None)
    parser.add_argument("--id_column", "--id-column", dest="id_column", default=None)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--window_size", "--window-size", dest="window_size", type=int, default=12)
    parser.add_argument("--test_size", "--test-size", dest="test_size", type=float, default=0.2)
    parser.add_argument("--valid_size", "--valid-size", dest="valid_size", type=float, default=0.1)
    parser.add_argument("--frequency_policy", "--frequency-policy", dest="frequency_policy", default="strict")
    parser.add_argument("--resample_frequency", "--resample-frequency", dest="resample_frequency", default=None)
    parser.add_argument("--fill_method", "--fill-method", dest="fill_method", default="ffill")
    parser.add_argument("--backtest_mode", "--backtest-mode", dest="backtest_mode", default="simple_holdout")
    parser.add_argument("--rolling_train_min_size", "--rolling-train-min-size", dest="rolling_train_min_size", type=int, default=24)
    parser.add_argument("--rolling_step_size", "--rolling-step-size", dest="rolling_step_size", type=int, default=1)
'''
        return f'''from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stable orchestrator entrypoint for run-scoped experiments.")
    parser.add_argument("--output_root", "--out_root", "--output-path", dest="output_root", default=".")
    parser.add_argument("--data_root", "--data-root", dest="data_root", default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--epochs", "--max_epochs", dest="epochs", type=int, default=1)
    parser.add_argument("--batch_size", "--batch-size", dest="batch_size", type=int, default=32)
    parser.add_argument("--num_workers", "--num-workers", dest="num_workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run_all", "--run-all", dest="run_all", action="store_true")
    parser.add_argument("--exp_id", "--exp-id", dest="exp_id", default=None)
    parser.add_argument("--exp_name", "--exp-name", dest="exp_name", default=None)
    parser.add_argument("--validation_tier", "--validation-tier", dest="validation_tier", default="smoke")
    parser.add_argument("--dataset_origin", "--dataset-origin", dest="dataset_origin", default="unknown")
    parser.add_argument("--evaluation_scope", "--evaluation-scope", dest="evaluation_scope", default="unknown")
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--attempt_id", "--attempt-id", dest="attempt_id", default="")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
{extra_args.rstrip()}
    return parser


def parse_args() -> argparse.Namespace:
    args, _unknown = build_parser().parse_known_args()
    args.output_root = str(Path(args.output_root))
    if args.data_root is not None:
        args.data_root = str(Path(args.data_root))
    # Absorb extra --key value pairs from unknown args into namespace
    i = 0
    while i < len(_unknown):
        tok = _unknown[i]
        if tok.startswith("--"):
            dest = tok.lstrip("-").replace("-", "_")
            if i + 1 < len(_unknown) and not _unknown[i + 1].startswith("--"):
                setattr(args, dest, _unknown[i + 1])
                i += 2
            else:
                setattr(args, dest, True)
                i += 1
        else:
            i += 1
    return args
'''

    @staticmethod
    def _render_config_schema_py(scaffold_type: str) -> str:
        return '''from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RuntimeContext:
    run_id: str
    output_root: Path
    results_root: Path
    reports_root: Path
    logs_root: Path
    data_root: Optional[Path]
    device: str
    epochs: int
    batch_size: int
    num_workers: int
    seed: int
    validation_tier: str
    dataset_origin: str
    evaluation_scope: str
    script_path: str = ""
    script_args: str = ""
    working_dir: str = ""
    iteration: Optional[int] = None
    attempt_id: str = ""
'''

    @staticmethod
    def _render_artifacts_py() -> str:
        return '''from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return _json_safe_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, set):
        return [_json_safe_value(item) for item in sorted(value, key=lambda item: str(item))]
    if hasattr(value, "__fspath__"):
        try:
            return Path(value).as_posix()
        except Exception:
            return str(value)
    if hasattr(value, "__dict__"):
        return _json_safe_value(dict(value.__dict__))
    return str(value)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _json_safe_value(payload)
    path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _safe_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_.")
    return cleaned or "default"


def write_result_json(
    *,
    output_root: Path,
    payload: Dict[str, Any],
    run_id: str,
    iteration: int | None = None,
    attempt_id: str = "",
) -> Path:
    results_root = ensure_dir(output_root / "results")
    stamped = dict(payload)
    stamped.setdefault("run_id", run_id)
    stamped.setdefault("iteration", iteration)
    stamped.setdefault("attempt_id", attempt_id)
    stamped.setdefault("created_at", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    result_path = results_root / "result.json"
    write_json(result_path, stamped)
    created_token = _safe_filename_component(str(stamped.get("created_at", "")))
    write_json(results_root / f"result_at_{created_token}.json", stamped)
    if iteration is not None:
        write_json(results_root / f"result_iteration_{int(iteration)}.json", stamped)
    if str(attempt_id or "").strip():
        write_json(results_root / f"result_attempt_{_safe_filename_component(attempt_id)}.json", stamped)
    return result_path
'''

    @staticmethod
    def _render_metrics_py() -> str:
        """batch_topk_accuracies 를 포함한 안정적인 metrics 구현체.

        evaluate.py / train.py 가 이 함수를 import 한다.
        LLM 이 metrics.py 를 다시 쓰면 함수명이 달라지는 사례가 반복됐으므로
        scaffold stable 파일로 제공해 불일치를 원천 차단한다.
        """
        return '''from __future__ import annotations

import torch
from typing import Iterable


def batch_topk_accuracies(
    logits: torch.Tensor,
    targets: torch.Tensor,
    topk: Iterable[int] = (1, 5),
) -> dict[str, float]:
    """Compute top-k accuracies for a batch of logits and integer targets.

    Returns a mapping from "top{k}_accuracy" to accuracy in [0, 1].
    Example: {"top1_accuracy": 0.72, "top5_accuracy": 0.95}

    Note: returns STRING keys, not integer keys.
    Access via result["top1_accuracy"], NOT result[1].
    """
    topk_list = list(topk)
    with torch.no_grad():
        maxk = max(topk_list)
        batch_size = targets.size(0)
        if batch_size == 0:
            return {f"top{k}_accuracy": 0.0 for k in topk_list}

        _, pred = logits.topk(min(maxk, logits.size(-1)), dim=1, largest=True, sorted=True)
        pred = pred.t()
        correct = pred.eq(targets.view(1, -1).expand_as(pred))

        result: dict[str, float] = {}
        for k in topk_list:
            k_clamped = min(k, logits.size(-1))
            correct_k = correct[:k_clamped].reshape(-1).float().sum(0, keepdim=True)
            result[f"top{k}_accuracy"] = float(correct_k.item()) / batch_size
        return result


class AverageMeter:
    """Track running average of a scalar metric (loss, accuracy, …)."""

    def __init__(self, name: str | None = None):
        self.name = name or "metric"
        self.reset()

    def reset(self) -> None:
        self.val = 0.0
        self.avg = 0.0
        self.sum = 0.0
        self.count = 0

    def update(self, value: float, n: int = 1) -> None:
        self.val = float(value)
        self.sum += float(value) * n
        self.count += n
        self.avg = self.sum / self.count if self.count > 0 else 0.0

    def __repr__(self) -> str:
        return f"AverageMeter({self.name!r}, avg={self.avg:.4f}, n={self.count})"
'''

    def _render_main_py(self) -> str:
        return '''from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any, Dict

from artifacts import write_result_json
from cli import parse_args
from config_schema import RuntimeContext
import experiment_impl


def _build_runtime_context(args) -> RuntimeContext:
    output_root = Path(args.output_root).resolve()
    return RuntimeContext(
        run_id=output_root.name if output_root.name else output_root.parent.name,
        output_root=output_root,
        results_root=output_root / "results",
        reports_root=output_root / "reports",
        logs_root=output_root / "logs",
        data_root=Path(args.data_root).resolve() if getattr(args, "data_root", None) else None,
        script_path=str(getattr(args, "script_path", "") or ""),
        script_args=str(getattr(args, "script_args", "") or ""),
        working_dir=str(getattr(args, "working_dir", "") or ""),
        iteration=int(os.environ["RESEARCH_ITERATION"]) if os.environ.get("RESEARCH_ITERATION") else None,
        attempt_id=str(os.environ.get("RESEARCH_ATTEMPT_ID", "")),
        device=str(getattr(args, "device", "cpu")),
        epochs=int(getattr(args, "epochs", 1)),
        batch_size=int(getattr(args, "batch_size", 32)),
        num_workers=int(getattr(args, "num_workers", 0)),
        seed=int(getattr(args, "seed", 42)),
        validation_tier=str(getattr(args, "validation_tier", "smoke")),
        dataset_origin=str(getattr(args, "dataset_origin", "unknown")),
        evaluation_scope=str(getattr(args, "evaluation_scope", "unknown")),
    )


def _normalize_success_payload(raw_result: Any, runtime_context: RuntimeContext) -> Dict[str, Any]:
    if isinstance(raw_result, dict):
        payload = dict(raw_result)
    else:
        payload = {"result": raw_result}
    payload.setdefault("execution_success", True)
    payload.setdefault("validation_tier", runtime_context.validation_tier)
    payload.setdefault("dataset_origin", runtime_context.dataset_origin)
    payload.setdefault("evaluation_scope", runtime_context.evaluation_scope)
    return payload


def _normalize_failure_payload(exc: BaseException, runtime_context: RuntimeContext) -> Dict[str, Any]:
    return {
        "execution_success": False,
        "validation_tier": "failed",
        "dataset_origin": runtime_context.dataset_origin,
        "evaluation_scope": runtime_context.evaluation_scope,
        "error_type": exc.__class__.__name__,
        "error_summary": str(exc),
        "traceback": traceback.format_exc(),
    }


def main() -> int:
    args = parse_args()
    runtime_context = _build_runtime_context(args)
    try:
        raw_result = experiment_impl.run_selected_experiments(args, runtime_context)
        payload = _normalize_success_payload(raw_result, runtime_context)
        write_result_json(
            output_root=runtime_context.output_root,
            payload=payload,
            run_id=runtime_context.run_id,
            iteration=runtime_context.iteration,
            attempt_id=runtime_context.attempt_id,
        )
        return 0
    except Exception as exc:
        payload = _normalize_failure_payload(exc, runtime_context)
        write_result_json(
            output_root=runtime_context.output_root,
            payload=payload,
            run_id=runtime_context.run_id,
            iteration=runtime_context.iteration,
            attempt_id=runtime_context.attempt_id,
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
'''


    @staticmethod
    def _render_contract_smoke_test() -> str:
        return '''from __future__ import annotations

from pathlib import Path


def test_workspace_contract_files_exist() -> None:
    workspace_root = Path(__file__).resolve().parents[1]
    assert (workspace_root / "src" / "main.py").exists()
    assert (workspace_root / "src" / "cli.py").exists()
    assert (workspace_root / "src" / "experiment_impl.py").exists()
    assert (workspace_root / "src" / "experiment_registry.py").exists()
    assert (workspace_root / "src" / "result_reducer.py").exists()
    assert (workspace_root / "src" / "validation.py").exists()
'''

    @staticmethod
    def _render_cli_contract_test() -> str:
        return '''from __future__ import annotations

import importlib.util
from pathlib import Path


def test_cli_module_imports() -> None:
    cli_path = Path(__file__).resolve().parents[1] / "src" / "cli.py"
    spec = importlib.util.spec_from_file_location("workspace_cli", cli_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert hasattr(module, "build_parser")
    assert hasattr(module, "parse_args")
'''

