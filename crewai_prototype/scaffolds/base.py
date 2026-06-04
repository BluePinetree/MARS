from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ScaffoldMaterialization:
    scaffold_type: str
    workspace_root: Path
    src_root: Path
    tests_root: Path
    logs_root: Path
    results_root: Path
    reports_root: Path
    entrypoint_path: Path
    mutable_module_path: Path
    manifest_path: Path
    run_contract_path: Path
