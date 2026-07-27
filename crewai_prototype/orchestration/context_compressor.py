"""orchestration/context_compressor.py — Phase 경계 데이터 압축.

Phase 3의 stdout/stderr을 그대로 Writer에게 넘기면 컨텍스트가 폭발한다.
이 모듈이 500자 이내로 잘라 ExecutorResultSummary / WriterContext를 구성한다.
"""
from __future__ import annotations

from core.handoff_models import (
    CodingHandoffSummary,
    CodingResult,
    ExecutorResult,
    ExecutorResultSummary,
    PlanBundle,
    WriterContext,
)

MAX_STDOUT_CHARS = 500
MAX_STDERR_CHARS = 500
MAX_METRICS_ENTRIES = 30  # flat 항목 최대 개수


def _flatten_metrics(metrics: dict) -> dict:
    """result.json에서 flat 숫자/문자열 값만 추출한다.

    중첩 dict/list (per-run 스펙, adversarial config 등)는 제거.
    Writer에 필요한 것은 최종 성능 수치뿐이다.
    """
    if not metrics:
        return {}
    flat: dict = {}
    for k, v in metrics.items():
        if isinstance(v, (int, float, str, bool)):
            flat[k] = v
        elif isinstance(v, dict):
            # 한 단계 내려가서 flat 값만 꺼냄 (예: {"resnet18": {"accuracy": 0.92}})
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, (int, float, str, bool)):
                    flat[f"{k}.{sub_k}"] = sub_v
        if len(flat) >= MAX_METRICS_ENTRIES:
            flat["__truncated__"] = f"(showing {MAX_METRICS_ENTRIES} of {len(metrics)} keys)"
            break
    return flat


class ContextCompressor:
    """Phase 경계에서 대용량 텍스트를 압축해 다음 Phase 컨텍스트 크기를 제한한다."""

    def compress_executor_result(self, result: ExecutorResult) -> ExecutorResultSummary:
        """ExecutorResult → ExecutorResultSummary (stdout/stderr 최대 500자).

        metrics는 flat 숫자/문자열 값만 추출한다.
        result.json 전체(중첩 구조, per-run 스펙)를 그대로 넘기면
        Writer 프롬프트가 수십만 토큰으로 폭발하기 때문.
        """
        return ExecutorResultSummary(
            return_code=result.return_code,
            duration_s=result.duration_s,
            metrics=_flatten_metrics(result.metrics),
            stdout_excerpt=result.stdout_tail[-MAX_STDOUT_CHARS:] if result.stdout_tail else "",
            stderr_excerpt=result.stderr_tail[-MAX_STDERR_CHARS:] if result.stderr_tail else "",
            artifact_paths=result.artifact_paths,
            result_json_path=result.result_json_path,
            success=result.success,
        )

    def compress_coding_result(self, coding_result: CodingResult) -> CodingHandoffSummary:
        """CodingResult → CodingHandoffSummary (파일 수 / 실패 목록 / repair 횟수)."""
        total_files = sum(len(s.files) for s in coding_result.stages)
        failed_files = [
            fr.path
            for s in coding_result.stages
            for fr in s.files
            if not fr.check.passed
        ]
        total_repairs = sum(
            len(fr.repair_records)
            for s in coding_result.stages
            for fr in s.files
        )
        return CodingHandoffSummary(
            total_files=total_files,
            failed_files=failed_files,
            total_repair_attempts=total_repairs,
            smoke_test_passed=coding_result.smoke_test_passed,
            import_check_passed=coding_result.all_stages_passed,
        )

    def build_writer_context(
        self,
        plan: PlanBundle,
        coding_result: CodingResult,
        exec_result: ExecutorResult,
        analysis_summary: str = "",
    ) -> WriterContext:
        """모든 Phase 결과를 Writer가 사용할 압축 컨텍스트로 변환한다."""
        plan_summary = (
            f"Topic: {plan.planner.problem_statement}\n"
            f"Criteria: {'; '.join(plan.planner.success_criteria[:3])}"
        )
        design_summary = (
            f"Entry: {plan.designer.entry_point}\n"
            f"Files: {len(plan.designer.files)}\n"
            f"Family: {plan.designer.experiment_family}"
        )
        return WriterContext(
            plan_summary=plan_summary,
            design_summary=design_summary,
            coding_summary=self.compress_coding_result(coding_result),
            exec_summary=self.compress_executor_result(exec_result),
            analysis_summary=analysis_summary,
        )
