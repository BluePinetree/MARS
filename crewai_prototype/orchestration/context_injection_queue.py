"""orchestration/context_injection_queue.py — 런타임 중 컨텍스트 주입 큐.

UI에서 사용자가 추가 정보를 주입하면 해당 Phase에서 꺼내 사용한다.
CheckpointManager.save()와 동시에 저장해 크래시 시에도 유실되지 않는다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_QUEUE_FILE = "injection_queue.json"


@dataclass
class InjectionItem:
    phase: int          # 적용할 Phase 번호 (0=즉시, -1=모든 Phase)
    context: str        # 추가 컨텍스트 텍스트
    source: str = "user"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InjectionItem":
        return cls(
            phase=int(d.get("phase", -1)),
            context=str(d.get("context", "")),
            source=str(d.get("source", "user")),
        )


class ContextInjectionQueue:
    """런타임 중 사용자가 추가 컨텍스트를 주입하는 큐.

    push(): UI → 큐에 추가 (나중에 특정 Phase에서 소비)
    pop_for_phase(): 해당 Phase에 맞는 항목 꺼내기 (소비 후 제거)
    persist(): checkpoint와 동시에 저장
    """

    def __init__(self) -> None:
        self._items: list[InjectionItem] = []

    def push(self, context: str, phase: int = -1, source: str = "user") -> None:
        """컨텍스트를 큐에 추가한다. phase=-1이면 모든 Phase에서 사용 가능."""
        item = InjectionItem(phase=phase, context=context, source=source)
        self._items.append(item)
        logger.debug("InjectionQueue push: phase=%d len=%d", phase, len(self._items))

    def pop_for_phase(self, phase: int) -> list[str]:
        """해당 phase 또는 -1(전체)에 해당하는 항목을 소비하고 반환한다."""
        matched: list[InjectionItem] = []
        remaining: list[InjectionItem] = []
        for item in self._items:
            if item.phase == phase or item.phase == -1:
                matched.append(item)
            else:
                remaining.append(item)
        self._items = remaining
        if matched:
            logger.debug(
                "InjectionQueue pop_for_phase=%d: consumed %d items", phase, len(matched)
            )
        return [item.context for item in matched]

    def to_list(self) -> list[dict]:
        """CheckpointManager.save()에 전달할 직렬화 형태."""
        return [item.to_dict() for item in self._items]

    def load_from_list(self, data: list[dict]) -> None:
        """CheckpointManager.load_queue()에서 복원한 데이터로 초기화."""
        self._items = [InjectionItem.from_dict(d) for d in data if isinstance(d, dict)]

    def persist(self, run_id: str, handoff_dir: str | Path) -> None:
        """CheckpointManager.save()와 동시에 호출해야 한다."""
        p = Path(handoff_dir) / _QUEUE_FILE
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_list(), indent=2), encoding="utf-8")
            tmp.replace(p)
        except Exception:
            logger.exception("Failed to persist injection queue for run=%s", run_id)

    def __len__(self) -> int:
        return len(self._items)
