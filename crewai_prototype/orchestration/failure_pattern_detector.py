"""orchestration/failure_pattern_detector.py — Phase 3 반복 장애 감지.

OOM / Timeout이 REPEAT_THRESHOLD 회 이상 반복되면 should_escalate() == True.
repair loop 재진입 없이 GuidanceGate로 직행시킨다.
"""
from __future__ import annotations

import logging
from collections import Counter

from orchestration.error_classifier import ErrorClassifier, ErrorKind

logger = logging.getLogger(__name__)


class FailurePatternDetector:
    """Phase 3 실행 시도 이력에서 OOM / timeout 반복을 감지한다."""

    REPEAT_THRESHOLD = 2

    def __init__(self) -> None:
        self._history: list[ErrorKind] = []
        self._classifier = ErrorClassifier()

    def record(self, stderr: str, return_code: int = -1) -> ErrorKind:
        """stderr과 return_code를 분석해 이력에 추가하고 분류 결과를 반환한다."""
        kind = self._classifier.classify(stderr, return_code)
        self._history.append(kind)
        logger.debug(
            "FailurePatternDetector: recorded=%s total_attempts=%d", kind.value, len(self._history)
        )
        return kind

    def should_escalate(self) -> bool:
        """OOM 또는 TIMEOUT이 REPEAT_THRESHOLD 이상이면 True."""
        counts = Counter(self._history)
        for kind in (ErrorKind.OOM, ErrorKind.TIMEOUT):
            if counts[kind] >= self.REPEAT_THRESHOLD:
                logger.info(
                    "FailurePatternDetector: escalating — %s repeated %d times",
                    kind.value, counts[kind],
                )
                return True
        return False

    def latest_kind(self) -> ErrorKind:
        """가장 최근 기록된 ErrorKind를 반환한다."""
        return self._history[-1] if self._history else ErrorKind.UNKNOWN

    def summary(self) -> str:
        """이력 요약 문자열 (GuidanceGate emit용)."""
        counts = Counter(k.value for k in self._history)
        total = len(self._history)
        parts = [f"{k}×{v}" for k, v in counts.items()]
        return f"Total attempts: {total} — {', '.join(parts)}"

    def reset(self) -> None:
        """사용자가 GuidanceGate를 통해 재시도를 허가한 후 호출해 이력을 초기화한다."""
        self._history.clear()
        logger.debug("FailurePatternDetector: history reset")
