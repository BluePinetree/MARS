"""orchestration/extension_proposer.py — 실험 완료 후 추가 실험 제안.

실행/분석 결과를 바탕으로 추가 실험을 최대 3개 제안한다.
실제 실행 여부는 사용자가 UI에서 결정한다 — 이 모듈은 제안만 한다.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Callable, Optional

from core.handoff_models import ExecutorResultSummary

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]

MAX_PROPOSALS = 3


class ExtensionProposer:
    """실험 완료 후 추가 실험 아이디어를 LLM으로 생성하고 emit한다.

    실행 결정은 사용자 몫이므로 여기서는 제안 목록만 반환한다.
    """

    def propose(
        self,
        exec_summary: ExecutorResultSummary,
        analysis_summary: str,
        emit: EmitFn,
        llm=None,
    ) -> list[str]:
        """추가 실험 최대 MAX_PROPOSALS개를 제안하고 emit 후 반환한다."""
        if llm is None:
            proposals = self._default_proposals(exec_summary)
        else:
            proposals = self._llm_proposals(exec_summary, analysis_summary, llm)

        emit(
            "extension_proposals",
            f"[ExtensionProposer] {len(proposals)} proposal(s) generated.",
            {
                "proposals": proposals,
                "exec_success": exec_summary.success,
                "metrics": exec_summary.metrics,
            },
        )
        return proposals

    def _llm_proposals(
        self,
        exec_summary: ExecutorResultSummary,
        analysis_summary: str,
        llm,
    ) -> list[str]:
        metrics_str = _json.dumps(exec_summary.metrics, ensure_ascii=False)
        prompt = (
            f"Experiment result metrics: {metrics_str}\n"
            f"Analysis: {analysis_summary or '(none)'}\n\n"
            f"Propose up to {MAX_PROPOSALS} follow-up experiment ideas that could"
            " improve results or explore new directions. Keep each idea under 120 characters.\n"
            "Return a JSON array of strings: [\"idea 1\", \"idea 2\", ...]"
        )
        try:
            raw = llm.call([{"role": "user", "content": prompt}])
            if not isinstance(raw, str):
                raw = str(raw)
            cleaned = raw.strip().strip("`").lstrip("json").strip()
            data = _json.loads(cleaned)
            if isinstance(data, list):
                return [str(item) for item in data[:MAX_PROPOSALS]]
        except Exception as exc:
            logger.warning("ExtensionProposer LLM call failed (%s) — using defaults.", exc)
        return self._default_proposals(exec_summary)

    def _default_proposals(self, exec_summary: ExecutorResultSummary) -> list[str]:
        if not exec_summary.success:
            return [
                "Investigate and fix the experiment failure before extending.",
                "Add more detailed logging to identify the root cause.",
            ]
        return [
            "Run with a different random seed to verify reproducibility.",
            "Ablation study: disable one component at a time to measure individual contribution.",
            "Test on a held-out dataset to evaluate generalization.",
        ]
