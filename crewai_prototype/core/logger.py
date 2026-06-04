"""
core/logger.py
==============
표준 JSONL 로그 모듈.

system_common_spec.md에 정의된 표준 로그 이벤트 형식으로
모든 에이전트 행동과 대화를 기록합니다.

로그 형식:
  - 각 줄은 독립적인 JSON 객체 (JSONL)
  - 통합 UI에서 파싱하여 채팅 형식으로 시각화

이벤트 유형:
  SYSTEM_START, SYSTEM_END, AGENT_THINKING, AGENT_MESSAGE,
  TOOL_CALL, TOOL_RESULT, FILE_CREATED, CODE_BLOCK,
  EXPERIMENT_START, EXPERIMENT_RESULT, USER_QUESTION, PHASE_COMPLETE
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import get_config


# ── 에이전트 색상 코드 (UI 시각화용) ────────────────────
AGENT_COLORS = {
    "Research Planner": {"color": "#1E40AF", "bg": "#DBEAFE"},
    "Experiment Designer": {"color": "#7C3AED", "bg": "#EDE9FE"},
    "Code Generator": {"color": "#065F46", "bg": "#D1FAE5"},
    "Experiment Executor": {"color": "#92400E", "bg": "#FEF3C7"},
    "Result Analyzer": {"color": "#0F766E", "bg": "#CCFBF1"},
    "Paper Writer": {"color": "#9F1239", "bg": "#FFE4E6"},
    "Critic": {"color": "#DC2626", "bg": "#FEE2E2"},
    "System": {"color": "#374151", "bg": "#F3F4F6"},
}

# ── 유효한 이벤트 유형 ──────────────────────────────────
VALID_EVENT_TYPES = {
    "SYSTEM_START",
    "SYSTEM_END",
    "AGENT_THINKING",
    "AGENT_MESSAGE",
    "TOOL_CALL",
    "TOOL_RESULT",
    "FILE_CREATED",
    "CODE_BLOCK",
    "EXPERIMENT_START",
    "EXPERIMENT_RESULT",
    "USER_QUESTION",
    "PHASE_COMPLETE",
}


class ResearchLogger:
    """
    표준 JSONL 형식으로 연구 과정을 로깅하는 클래스.

    모든 로그는 {log_dir}/{run_id}.jsonl 파일에 기록되며,
    선택적으로 콘솔에도 출력됩니다.
    """

    def __init__(
        self,
        session_id: str = "crewai_session_001",
        run_id: Optional[str] = None,
        log_dir: Optional[str] = None,
        console_output: Optional[bool] = None,
    ):
        """
        Args:
            session_id: 세션 고유 ID
            run_id: 실행 고유 ID (None이면 자동 생성)
            log_dir: 로그 디렉토리 경로 (None이면 config에서 로드)
            console_output: 콘솔 출력 여부 (None이면 config에서 로드)
        """
        config = get_config()

        self.session_id = session_id
        self.run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.log_dir = Path(log_dir or config.logging.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.console_output = (
            console_output if console_output is not None else config.logging.console_output
        )

        self.log_file_path = str(self.log_dir / f"{self.run_id}.jsonl")
        self._start_time = time.time()

    def log(
        self,
        event_type: str,
        content: str,
        agent_name: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        표준 JSONL 형식으로 로그 이벤트를 기록합니다.

        Args:
            event_type: 이벤트 유형 (VALID_EVENT_TYPES 중 하나)
            content: 이벤트 내용
            agent_name: 이벤트를 발생시킨 에이전트 이름
            run_id: 실행 ID (None이면 인스턴스의 run_id 사용)
            metadata: 추가 메타데이터

        Returns:
            Dict: 기록된 로그 이벤트 객체
        """
        if event_type not in VALID_EVENT_TYPES:
            event_type = "AGENT_MESSAGE"  # 폴백

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "run_id": run_id or self.run_id,
            "event_type": event_type,
            "content": content,
        }

        if agent_name:
            event["agent_name"] = agent_name
            # UI 색상 정보 추가
            if agent_name in AGENT_COLORS:
                if metadata is None:
                    metadata = {}
                metadata["agent_color"] = AGENT_COLORS[agent_name]

        if metadata:
            event["metadata"] = metadata

        # JSONL 파일에 기록
        self._write_to_file(event)

        # 콘솔 출력
        if self.console_output:
            self._print_to_console(event)

        return event

    def _write_to_file(self, event: Dict[str, Any]):
        """JSONL 파일에 이벤트를 기록합니다."""
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[로그 기록 오류] {e}", file=sys.stderr)

    def _print_to_console(self, event: Dict[str, Any]):
        """콘솔에 포맷팅된 로그를 출력합니다."""
        event_type = event.get("event_type", "")
        agent = event.get("agent_name", "System")
        content = event.get("content", "")

        # 이벤트 유형별 아이콘
        icons = {
            "SYSTEM_START": "🚀",
            "SYSTEM_END": "🏁",
            "AGENT_THINKING": "💭",
            "AGENT_MESSAGE": "💬",
            "TOOL_CALL": "🔧",
            "TOOL_RESULT": "📋",
            "FILE_CREATED": "📄",
            "CODE_BLOCK": "💻",
            "EXPERIMENT_START": "🧪",
            "EXPERIMENT_RESULT": "📊",
            "USER_QUESTION": "❓",
            "PHASE_COMPLETE": "✅",
        }

        icon = icons.get(event_type, "📝")
        timestamp = event.get("timestamp", "")[:19]

        # 내용이 길면 잘라서 표시
        display_content = content[:200] + "..." if len(content) > 200 else content

        print(f"  {icon} [{timestamp}] [{agent}] {display_content}")

    # ── 편의 메서드 ─────────────────────────────────────

    def system_start(self, content: str, **kwargs):
        """시스템 시작 이벤트를 기록합니다."""
        return self.log("SYSTEM_START", content, agent_name="System", **kwargs)

    def system_end(self, content: str, status: str = "success", **kwargs):
        """시스템 종료 이벤트를 기록합니다."""
        elapsed = time.time() - self._start_time
        return self.log(
            "SYSTEM_END",
            content,
            agent_name="System",
            metadata={"status": status, "elapsed_seconds": round(elapsed, 2)},
            **kwargs,
        )

    def agent_thinking(self, agent_name: str, content: str, **kwargs):
        """에이전트 사고 과정을 기록합니다."""
        return self.log("AGENT_THINKING", content, agent_name=agent_name, **kwargs)

    def agent_message(self, agent_name: str, content: str, **kwargs):
        """에이전트 메시지를 기록합니다."""
        return self.log("AGENT_MESSAGE", content, agent_name=agent_name, **kwargs)

    def tool_call(
        self, agent_name: str, tool_name: str, tool_input: Any, **kwargs
    ):
        """도구 호출을 기록합니다."""
        return self.log(
            "TOOL_CALL",
            f"{tool_name} 도구를 호출합니다.",
            agent_name=agent_name,
            metadata={"tool_name": tool_name, "tool_input": str(tool_input)},
            **kwargs,
        )

    def tool_result(
        self, agent_name: str, content: str, success: bool = True, **kwargs
    ):
        """도구 호출 결과를 기록합니다."""
        return self.log(
            "TOOL_RESULT",
            content,
            agent_name=agent_name,
            metadata={"success": success},
            **kwargs,
        )

    def file_created(self, agent_name: str, file_path: str, **kwargs):
        """파일 생성 이벤트를 기록합니다."""
        return self.log(
            "FILE_CREATED",
            f"파일 생성: {file_path}",
            agent_name=agent_name,
            metadata={"file_path": file_path},
            **kwargs,
        )

    def code_block(
        self, agent_name: str, code: str, language: str = "python", **kwargs
    ):
        """코드 블록을 기록합니다."""
        return self.log(
            "CODE_BLOCK",
            code,
            agent_name=agent_name,
            metadata={"language": language},
            **kwargs,
        )

    def experiment_start(
        self, agent_name: str, experiment_id: str, **kwargs
    ):
        """실험 시작을 기록합니다."""
        return self.log(
            "EXPERIMENT_START",
            f"실험 시작: {experiment_id}",
            agent_name=agent_name,
            metadata={"experiment_id": experiment_id},
            **kwargs,
        )

    def experiment_result(
        self,
        agent_name: str,
        content: str,
        metrics: Optional[Dict[str, float]] = None,
        **kwargs,
    ):
        """실험 결과를 기록합니다."""
        return self.log(
            "EXPERIMENT_RESULT",
            content,
            agent_name=agent_name,
            metadata={"metrics": metrics or {}},
            **kwargs,
        )

    def phase_complete(
        self, phase_number: int, phase_name: str, **kwargs
    ):
        """구현 단계 완료를 기록합니다."""
        return self.log(
            "PHASE_COMPLETE",
            f"Phase {phase_number} 완료: {phase_name}",
            agent_name="System",
            metadata={
                "phase_number": phase_number,
                "phase_name": phase_name,
            },
            **kwargs,
        )

    def user_question(self, content: str, **kwargs):
        """사용자 질문을 기록합니다."""
        return self.log("USER_QUESTION", content, **kwargs)

    # ── 로그 읽기 ───────────────────────────────────────

    def read_logs(self, limit: int = 100) -> list:
        """로그 파일에서 최근 이벤트를 읽습니다."""
        log_path = Path(self.log_file_path)
        if not log_path.exists():
            return []

        events = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return events[-limit:]
