"""orchestration/token_budget_tracker.py — 토큰 예산 모니터링 (emit 전용).

경고: 이 모듈은 예산 소비를 모니터링하고 emit할 뿐이다.
     _MAX_DEP_CHARS / _MAX_TOTAL_DEP_CHARS 는 절대 런타임 중 변경하지 않는다.
     변경 시 Phase 2 내부 컨텍스트 불일치가 발생한다.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

EmitFn = Callable[[str, str, Optional[dict]], None]


class TokenBudgetTracker:
    """토큰 예산 소비량을 추적하고 임계치 초과 시 emit으로 경고한다.

    절대로 _MAX_DEP_CHARS 등 phase2_coding.py의 절단 상수를 수정하지 않는다.
    이 클래스는 관측(observe) 전용이다.
    """

    WARNING_THRESHOLD = 0.8   # 80% 소비 시 경고 emit

    def __init__(self, budget: int, emit: EmitFn) -> None:
        self._budget = budget
        self._used = 0
        self._emit = emit
        self._warned = False

    def record(self, chars: int, label: str = "") -> None:
        """chars 만큼 예산을 소비했음을 기록하고 필요 시 경고한다."""
        self._used += chars
        if self._budget <= 0:
            return
        ratio = self._used / self._budget
        if ratio >= self.WARNING_THRESHOLD and not self._warned:
            self._warned = True
            self._emit(
                "token_budget_warning",
                f"[TokenBudget] {ratio:.0%} of budget used"
                f" ({self._used}/{self._budget} chars){' — ' + label if label else ''}",
                {"used": self._used, "budget": self._budget, "ratio": ratio, "label": label},
            )
        logger.debug("TokenBudget: used=%d budget=%d ratio=%.2f label=%s",
                     self._used, self._budget, ratio, label)

    def snapshot(self) -> dict:
        """현재 예산 사용 상태를 dict로 반환한다 (emit용)."""
        ratio = self._used / self._budget if self._budget > 0 else 0.0
        return {
            "budget": self._budget,
            "used": self._used,
            "ratio": ratio,
        }

    def emit_snapshot(self, label: str = "") -> None:
        """현재 상태를 token_budget_snapshot 이벤트로 emit한다."""
        snap = self.snapshot()
        self._emit(
            "token_budget_snapshot",
            f"[TokenBudget] {snap['used']}/{snap['budget']} chars used ({snap['ratio']:.0%})"
            f"{' — ' + label if label else ''}",
            snap,
        )
