from __future__ import annotations

from typing import Any, Optional, Union
from pydantic import BaseModel, field_validator, model_validator


class RiskItem(BaseModel):
    risk: str
    mitigation: str = ""

    @classmethod
    def coerce(cls, v: Any) -> "RiskItem":
        if isinstance(v, str):
            return cls(risk=v, mitigation="")
        if isinstance(v, dict):
            return cls(risk=str(v.get("risk", v)), mitigation=str(v.get("mitigation", "")))
        return cls(risk=str(v), mitigation="")


class PlannerResult(BaseModel):
    problem_statement: str = ""
    research_questions: list[str] = []
    hypotheses: list[str] = []
    success_criteria: list[str] = []
    constraints: list[str] = []
    risks: list[Any] = []
    recommended_profile: str = "generic_script"
    next_stage_inputs: dict[str, Any] = {}

    @field_validator("risks", mode="before")
    @classmethod
    def _coerce_risks(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        coerced = []
        for item in v:
            if isinstance(item, dict):
                coerced.append({"risk": str(item.get("risk", item)), "mitigation": str(item.get("mitigation", ""))})
            elif isinstance(item, str):
                coerced.append({"risk": item, "mitigation": ""})
            else:
                coerced.append({"risk": str(item), "mitigation": ""})
        return coerced

    @field_validator("next_stage_inputs", mode="before")
    @classmethod
    def _coerce_next_stage(cls, v: Any) -> dict:
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return {}


class FileSpec(BaseModel):
    path: str
    responsibility: str = ""
    symbols: list[str] = []
    dependencies: list[str] = []
    mutable: bool = True

    @field_validator("symbols", "dependencies", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        if isinstance(v, list):
            return [str(x) for x in v]
        return []


class WorkspaceStructure(BaseModel):
    scaffold_type: str = "generic_python_experiment"
    files: list[FileSpec] = []
    generation_order: list[str] = []
    notes: list[str] = []

    @field_validator("files", mode="before")
    @classmethod
    def _coerce_files(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        coerced = []
        for item in v:
            if isinstance(item, dict) and "path" in item:
                coerced.append(item)
        return coerced

    @field_validator("generation_order", "notes", mode="before")
    @classmethod
    def _coerce_str_list(cls, v: Any) -> list:
        if isinstance(v, list):
            return [str(x) for x in v]
        return []


class DesignerResult(BaseModel):
    experiment_family: str = ""
    evaluation_protocol: dict = {}
    workspace_structure: WorkspaceStructure = WorkspaceStructure()

    @field_validator("evaluation_protocol", mode="before")
    @classmethod
    def _coerce_eval_protocol(cls, v: Any) -> dict:
        return v if isinstance(v, dict) else {}

    @field_validator("workspace_structure", mode="before")
    @classmethod
    def _coerce_ws(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return v
        return {}


class RepairAction(BaseModel):
    path: str
    symbol: Optional[str] = None
    reason: str


class AnalyzerResult(BaseModel):
    execution_success: bool
    primary_metric_value: Optional[float] = None
    failure_diagnosis: str = ""
    fix_instructions: list[str] = []
    repair_actions: list[RepairAction] = []
    should_continue: bool


# ---------------------------------------------------------------------------
# Contract-First Pipeline models
# ---------------------------------------------------------------------------

class SymbolSpec(BaseModel):
    name: str
    kind: str = "function"  # "function" | "class" | "variable"
    signature: Optional[str] = None


class ImportRef(BaseModel):
    from_path: str
    symbols: list[str]


class FileContract(BaseModel):
    path: str
    exports: list[SymbolSpec] = []
    imports: list[ImportRef] = []


class InterfaceContract(BaseModel):
    schema_version: str = "1.0"
    files: list[FileContract] = []


# ---------------------------------------------------------------------------
# V4 Pipeline handoff models
# ---------------------------------------------------------------------------

class WorkspaceConfig(BaseModel):
    """Phase 0 output: workspace directory setup result."""
    run_id: str
    root_dir: str           # absolute path
    workspace_dir: str      # root_dir/workspace/
    paper_dir: str          # root_dir/paper/
    handoff_dir: str        # root_dir/handoff/
    logs_dir: str = ""      # root_dir/logs/
    user_specified: bool = False


class FileNodeSpec(BaseModel):
    """AST-level file specification for V4 Designer."""
    path: str               # relative to workspace/
    responsibility: str = ""
    exports: list[str] = []         # function/class names this file exposes
    imports_from: list[str] = []    # other files in workspace it imports from
    stage: int = 1                  # 1=config/utils, 2=data/model, 3=entry point
    mutable: bool = True

    @field_validator("exports", "imports_from", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        if isinstance(v, list):
            return [str(x) for x in v]
        return []


class DesignerResultV4(BaseModel):
    """Phase 1 Designer output for V4 pipeline."""
    experiment_family: str = ""
    entry_point: str = "src/main.py"    # script to run in Phase 3
    files: list[FileNodeSpec] = []
    generation_order: list[str] = []    # dependency-sorted file paths
    stage_assignments: dict[str, int] = {}  # file_path → stage number
    import_graph: dict[str, list[str]] = {}  # file_path → [files it imports]
    success_criteria: list[str] = []
    notes: list[str] = []

    @field_validator("files", mode="before")
    @classmethod
    def _coerce_files(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [item for item in v if isinstance(item, dict) and "path" in item]

    @model_validator(mode="after")
    def _derive_stage_assignments(self) -> "DesignerResultV4":
        if not self.stage_assignments:
            for f in self.files:
                self.stage_assignments[f.path] = f.stage
        return self


class PlanBundle(BaseModel):
    """Combined Phase 1 output: planner + designer results for user approval."""
    planner: PlannerResult
    designer: DesignerResultV4
    workspace: WorkspaceConfig


class CheckResult(BaseModel):
    """Result of a syntax or import check on a file."""
    passed: bool
    error: str = ""
    error_type: str = ""    # "syntax" | "import" | "runtime" | ""
    line_no: Optional[int] = None


class RepairRecord(BaseModel):
    """Log entry for a single repair attempt."""
    attempt: int
    error_before: str
    fix_applied: str = ""
    passed: bool
    user_hint: str = ""


class FileResult(BaseModel):
    """Per-file coding outcome."""
    path: str
    written: bool
    check: CheckResult
    repair_records: list[RepairRecord] = []
    escalated_to_user: bool = False


class StageCodingResult(BaseModel):
    """Outcome for a single coding stage (1, 2, or 3)."""
    stage: int
    files: list[FileResult] = []

    @property
    def all_passed(self) -> bool:
        return all(f.check.passed for f in self.files if f.written)


class CodingResult(BaseModel):
    """Phase 2 full output."""
    stages: list[StageCodingResult] = []
    smoke_test_passed: bool = False
    smoke_test_error: str = ""

    @property
    def all_stages_passed(self) -> bool:
        return all(s.all_passed for s in self.stages)


class ExecutorResult(BaseModel):
    """Phase 3 output."""
    success: bool
    return_code: int = -1
    metrics: dict[str, Any] = {}
    artifact_paths: list[str] = []
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_s: float = 0.0
    result_json_path: str = ""


class SectionResult(BaseModel):
    """Per-section paper writing outcome."""
    section: str
    content: str = ""
    quality_score: float = 0.0
    revisions: int = 0
    needs_review: bool = False


class WritingResult(BaseModel):
    """Phase 4 full output."""
    paper_path: str = ""
    sections: list[SectionResult] = []
    overall_quality: float = 0.0


# ---------------------------------------------------------------------------
# Sprint 2: Context compression handoff models
# ---------------------------------------------------------------------------

class CodingHandoffSummary(BaseModel):
    """Phase 2 → Phase 4 압축 요약 (WriterContext에 포함)."""
    total_files: int = 0
    failed_files: list[str] = []
    total_repair_attempts: int = 0
    smoke_test_passed: bool = False
    import_check_passed: bool = False


class ExecutorResultSummary(BaseModel):
    """Phase 3 → Phase 4에 전달되는 압축 요약.

    stdout_tail / stderr_tail을 최대 500자로 잘라서 Writer 컨텍스트 폭발을 방지한다.
    metrics dict는 원본 그대로 유지한다.
    """
    return_code: int = -1
    duration_s: float = 0.0
    metrics: dict[str, Any] = {}
    stdout_excerpt: str = ""    # 최대 500자
    stderr_excerpt: str = ""    # 최대 500자
    artifact_paths: list[str] = []
    result_json_path: str = ""
    success: bool = False


class WriterContext(BaseModel):
    """Writer가 논문 작성에 필요한 모든 정보를 담은 압축 컨텍스트."""
    plan_summary: str = ""          # Phase 0/1 플랜 요약
    design_summary: str = ""        # Phase 1 설계 요약
    coding_summary: CodingHandoffSummary = CodingHandoffSummary()
    exec_summary: ExecutorResultSummary = ExecutorResultSummary()
    analysis_summary: str = ""      # Phase 3.5 분석 요약
