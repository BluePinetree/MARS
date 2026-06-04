"""orchestration/preflight_clarifier.py — 실행 전 사전 명확화 (최대 4문항).

실행 전 연구 주제의 불명확한 부분을 최대 4문항으로 물어본다.
모든 문항에는 기본값이 있으므로 사용자가 응답하지 않아도 진행 가능하다.
60초 타임아웃 → 기본값 자동 사용.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from orchestration.approval_registry import GuidanceGate, GuidanceRegistry

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]


@dataclass
class PreflightQuestion:
    key: str
    text: str
    default: str


class PreflightClarifier:
    """실행 전 최대 4문항으로 연구 방향을 명확화한다.

    GuidanceGate 패턴을 재사용하므로 UI에서 동일한 guidance 엔드포인트로 응답 가능.
    """

    MAX_QUESTIONS = 4
    TIMEOUT_PER_QUESTION_SECS = 60

    def run(
        self,
        run_id: str,
        research_topic: str,
        plan_summary: str,
        guidance_registry: GuidanceRegistry,
        emit: EmitFn,
        llm=None,
    ) -> dict[str, str]:
        """최대 MAX_QUESTIONS개 질문을 순서대로 묻고 답을 반환한다.

        사용자 무응답(TIMEOUT_PER_QUESTION_SECS) → 기본값으로 자동 진행.
        LLM이 없으면 내장 질문 목록을 사용한다.
        """
        questions = self._generate_questions(research_topic, plan_summary, llm)
        answers: dict[str, str] = {}

        for q in questions:
            gate_key = f"preflight_{q.key}"
            gate = GuidanceGate(
                file_path=gate_key,
                error_msg=f"Preflight question: {q.text}",
                attempt_count=0,
            )
            guidance_registry.register(run_id, gate_key, gate)

            emit(
                "PREFLIGHT_QUESTION",
                f"[Preflight] {q.text}",
                {
                    "run_id": run_id,
                    "question_key": q.key,
                    "question": q.text,
                    "default": q.default,
                    "timeout_secs": self.TIMEOUT_PER_QUESTION_SECS,
                    "options": ["continue", "provide_fix"],
                },
            )

            answered = gate.wait(timeout=self.TIMEOUT_PER_QUESTION_SECS)
            guidance_registry.remove(run_id, gate_key)

            if answered and gate.hint:
                answers[q.key] = gate.hint
                emit(
                    "PREFLIGHT_ANSWERED",
                    f"[Preflight] {q.key}: {gate.hint[:100]}",
                    {"question_key": q.key, "answer": gate.hint},
                )
            else:
                answers[q.key] = q.default
                emit(
                    "PREFLIGHT_ANSWERED",
                    f"[Preflight] {q.key}: (default) {q.default}",
                    {"question_key": q.key, "answer": q.default, "used_default": True},
                )

        return answers

    def _generate_questions(
        self,
        research_topic: str,
        plan_summary: str,
        llm=None,
    ) -> list[PreflightQuestion]:
        """LLM이 있으면 주제 기반으로 질문 생성, 없으면 범용 질문 사용."""
        if llm is not None:
            return self._llm_questions(research_topic, plan_summary, llm)
        return self._default_questions(research_topic)

    def _default_questions(self, topic: str) -> list[PreflightQuestion]:
        return [
            PreflightQuestion(
                key="dataset_constraint",
                text=f"'{topic}' 실험에서 사용할 데이터셋에 특별한 제약이 있나요? (없으면 기본값 사용)",
                default="No special constraints — use the dataset defined in the plan.",
            ),
            PreflightQuestion(
                key="compute_constraint",
                text="GPU 메모리나 CPU 코어 수 등 컴퓨팅 제약이 있나요?",
                default="No specific constraints — use available hardware.",
            ),
            PreflightQuestion(
                key="eval_metric",
                text="주요 평가 지표를 지정하고 싶은 게 있나요? (없으면 플랜 기본값 사용)",
                default="Use the evaluation metric defined in the design plan.",
            ),
            PreflightQuestion(
                key="extra_context",
                text="추가로 실험에 반영해야 할 중요한 정보가 있나요?",
                default="No additional context.",
            ),
        ]

    def _llm_questions(
        self, topic: str, plan_summary: str, llm
    ) -> list[PreflightQuestion]:
        """LLM을 사용해 주제/플랜 기반 맞춤 질문을 생성한다."""
        import json as _json

        prompt = (
            f"Research topic: {topic}\n"
            f"Plan summary: {plan_summary}\n\n"
            "Generate up to 4 clarifying questions that would help make this experiment"
            " more stable and reproducible. Each question must have a sensible default answer.\n"
            "Return JSON array: "
            '[{"key": "...", "text": "...", "default": "..."}]\n'
            "Keep each question under 80 characters."
        )
        try:
            raw = llm.call([{"role": "user", "content": prompt}])
            if not isinstance(raw, str):
                raw = str(raw)
            data = _json.loads(raw.strip().strip("`").lstrip("json").strip())
            if isinstance(data, list):
                result = []
                for item in data[: self.MAX_QUESTIONS]:
                    if isinstance(item, dict) and "key" in item and "text" in item:
                        result.append(
                            PreflightQuestion(
                                key=str(item["key"]),
                                text=str(item["text"]),
                                default=str(item.get("default", "No preference.")),
                            )
                        )
                if result:
                    return result
        except Exception as exc:
            logger.warning("LLM question generation failed (%s) — using defaults.", exc)

        return self._default_questions(topic)
