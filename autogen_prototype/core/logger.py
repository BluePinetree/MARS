"""
표준 JSONL 로그 시스템

system_common_spec.md에 정의된 표준 JSONL 형식으로
에이전트 간 모든 대화와 도구 사용 내역을 로깅합니다.

이 로그는 추후 통합 UI에서 채팅 형식으로 시각화됩니다.

이벤트 유형:
- SYSTEM_START / SYSTEM_END
- AGENT_THINKING / AGENT_MESSAGE
- TOOL_CALL / TOOL_RESULT
- FILE_CREATED / CODE_BLOCK
- EXPERIMENT_START / EXPERIMENT_RESULT
- USER_QUESTION / PHASE_COMPLETE
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 이벤트 유형 상수
# ============================================================

class EventType:
    """표준 로그 이벤트 유형"""
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_END = "SYSTEM_END"
    AGENT_THINKING = "AGENT_THINKING"
    AGENT_MESSAGE = "AGENT_MESSAGE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    FILE_CREATED = "FILE_CREATED"
    CODE_BLOCK = "CODE_BLOCK"
    EXPERIMENT_START = "EXPERIMENT_START"
    EXPERIMENT_RESULT = "EXPERIMENT_RESULT"
    USER_QUESTION = "USER_QUESTION"
    PHASE_COMPLETE = "PHASE_COMPLETE"


# ============================================================
# 에이전트 색상 코드 (UI 시각화용)
# ============================================================

AGENT_COLORS = {
    "ResearchPlanner": {"name": "Deep Blue", "hex": "#1E40AF", "bg": "#DBEAFE"},
    "Coder": {"name": "Green", "hex": "#065F46", "bg": "#D1FAE5"},
    "Executor": {"name": "Orange", "hex": "#92400E", "bg": "#FEF3C7"},
    "Critic": {"name": "Red", "hex": "#DC2626", "bg": "#FEE2E2"},
    "System": {"name": "Gray", "hex": "#374151", "bg": "#F3F4F6"},
    "User": {"name": "Purple", "hex": "#7C3AED", "bg": "#EDE9FE"},
}


# ============================================================
# 연구 로거 클래스
# ============================================================

class ResearchLogger:
    """
    표준 JSONL 형식의 연구 로거.

    모든 에이전트 대화, 도구 호출, 실험 결과를 JSONL 파일에 기록합니다.
    각 로그 항목은 독립적인 JSON 객체로, 통합 UI에서 파싱하여 시각화됩니다.
    """

    def __init__(
        self,
        log_dir: str = "./logs",
        session_id: str = "autogen_session",
        run_id: str | None = None,
        console_output: bool = True,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._session_id = session_id
        self._run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._console_output = console_output

        # 로그 파일 경로
        self._log_file = self._log_dir / f"{self._run_id}.jsonl"
        self._event_count = 0

        # Rich 콘솔 (선택적)
        self._console = None
        if console_output:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                pass

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def log_file_path(self) -> str:
        return str(self._log_file)

    def _write_event(self, event: dict[str, Any]) -> None:
        """이벤트를 JSONL 파일에 기록합니다."""
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        self._event_count += 1

    def _format_console(self, event: dict[str, Any]) -> None:
        """콘솔에 이벤트를 포맷팅하여 출력합니다."""
        if not self._console_output:
            return

        event_type = event.get("event_type", "")
        agent_name = event.get("agent_name", "System")
        content = event.get("content", "")

        # 에이전트 색상
        color_info = AGENT_COLORS.get(agent_name, AGENT_COLORS["System"])

        if self._console:
            from rich.panel import Panel
            from rich.text import Text

            if event_type == EventType.SYSTEM_START:
                self._console.print(
                    Panel(content, title="🚀 시스템 시작", style="bold green")
                )
            elif event_type == EventType.SYSTEM_END:
                status = event.get("metadata", {}).get("status", "unknown")
                style = "bold green" if status == "success" else "bold red"
                self._console.print(
                    Panel(content, title="🏁 시스템 종료", style=style)
                )
            elif event_type == EventType.AGENT_MESSAGE:
                self._console.print(
                    f"[bold {color_info['hex']}]💬 [{agent_name}][/] {content[:200]}{'...' if len(content) > 200 else ''}"
                )
            elif event_type == EventType.AGENT_THINKING:
                self._console.print(
                    f"[dim]🤔 [{agent_name}] {content[:150]}{'...' if len(content) > 150 else ''}[/]"
                )
            elif event_type == EventType.TOOL_CALL:
                tool_name = event.get("metadata", {}).get("tool_name", "unknown")
                self._console.print(
                    f"[bold blue]🔧 [{agent_name}] 도구 호출: {tool_name}[/]"
                )
            elif event_type == EventType.TOOL_RESULT:
                success = event.get("metadata", {}).get("success", False)
                icon = "✅" if success else "❌"
                self._console.print(
                    f"[{'green' if success else 'red'}]{icon} [{agent_name}] 도구 결과: {content[:150]}[/]"
                )
            elif event_type == EventType.CODE_BLOCK:
                lang = event.get("metadata", {}).get("language", "python")
                self._console.print(
                    f"[bold green]📝 [{agent_name}] 코드 블록 ({lang})[/]"
                )
            elif event_type == EventType.EXPERIMENT_START:
                exp_id = event.get("metadata", {}).get("experiment_id", "")
                self._console.print(
                    f"[bold yellow]🧪 [{agent_name}] 실험 시작: {exp_id}[/]"
                )
            elif event_type == EventType.EXPERIMENT_RESULT:
                self._console.print(
                    f"[bold cyan]📊 [{agent_name}] 실험 결과[/]"
                )
            elif event_type == EventType.PHASE_COMPLETE:
                phase_name = event.get("metadata", {}).get("phase_name", "")
                self._console.print(
                    Panel(
                        f"✅ {phase_name}",
                        title="단계 완료",
                        style="bold green",
                    )
                )
            else:
                self._console.print(f"[{event_type}] {agent_name}: {content[:100]}")
        else:
            # Rich 미설치 시 기본 출력
            print(f"[{event_type}] [{agent_name}] {content[:200]}")

    def _create_event(
        self,
        event_type: str,
        content: str = "",
        agent_name: str = "System",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """표준 형식의 이벤트 딕셔너리를 생성합니다."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self._session_id,
            "run_id": self._run_id,
            "event_type": event_type,
            "agent_name": agent_name,
            "content": content,
        }
        if metadata:
            event["metadata"] = metadata
        return event

    # ============================================================
    # 공개 로깅 메서드
    # ============================================================

    def log_system_start(self, research_config: dict[str, Any]) -> None:
        """시스템 시작 이벤트를 기록합니다."""
        content = (
            f"자율 연구 시스템 시작 (AutoGen 아키텍처)\n"
            f"연구 주제: {research_config.get('research_topic', 'N/A')}\n"
            f"연구 목표: {research_config.get('research_goal', 'N/A')}\n"
            f"연구 분야: {research_config.get('research_domain', 'N/A')}"
        )
        event = self._create_event(
            EventType.SYSTEM_START,
            content=content,
            metadata={"research_config": research_config},
        )
        self._write_event(event)
        self._format_console(event)

    def log_system_end(self, status: str = "success", summary: str = "") -> None:
        """시스템 종료 이벤트를 기록합니다."""
        content = f"시스템 종료 ({status}). {summary}"
        event = self._create_event(
            EventType.SYSTEM_END,
            content=content,
            metadata={"status": status, "total_events": self._event_count},
        )
        self._write_event(event)
        self._format_console(event)

    def log_agent_message(
        self,
        agent_name: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """에이전트 간 대화 메시지를 기록합니다."""
        event = self._create_event(
            EventType.AGENT_MESSAGE,
            content=content,
            agent_name=agent_name,
            metadata=metadata,
        )
        self._write_event(event)
        self._format_console(event)

    def log_agent_thinking(
        self,
        agent_name: str,
        content: str,
    ) -> None:
        """에이전트 내부 사고 과정을 기록합니다."""
        event = self._create_event(
            EventType.AGENT_THINKING,
            content=content,
            agent_name=agent_name,
        )
        self._write_event(event)
        self._format_console(event)

    def log_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_input: Any,
    ) -> None:
        """도구 호출 시작을 기록합니다."""
        event = self._create_event(
            EventType.TOOL_CALL,
            content=f"도구 호출: {tool_name}",
            agent_name=agent_name,
            metadata={
                "tool_name": tool_name,
                "tool_input": str(tool_input)[:500],
            },
        )
        self._write_event(event)
        self._format_console(event)

    def log_tool_result(
        self,
        agent_name: str,
        tool_name: str,
        result: str,
        success: bool = True,
    ) -> None:
        """도구 호출 결과를 기록합니다."""
        event = self._create_event(
            EventType.TOOL_RESULT,
            content=result[:1000],
            agent_name=agent_name,
            metadata={
                "tool_name": tool_name,
                "success": success,
            },
        )
        self._write_event(event)
        self._format_console(event)

    def log_code_block(
        self,
        agent_name: str,
        code: str,
        language: str = "python",
        filename: str = "",
    ) -> None:
        """생성된 코드 블록을 기록합니다."""
        event = self._create_event(
            EventType.CODE_BLOCK,
            content=code,
            agent_name=agent_name,
            metadata={
                "language": language,
                "filename": filename,
            },
        )
        self._write_event(event)
        self._format_console(event)

    def log_file_created(
        self,
        agent_name: str,
        file_path: str,
        description: str = "",
    ) -> None:
        """파일 생성 이벤트를 기록합니다."""
        event = self._create_event(
            EventType.FILE_CREATED,
            content=description or f"파일 생성: {file_path}",
            agent_name=agent_name,
            metadata={"file_path": file_path},
        )
        self._write_event(event)
        self._format_console(event)

    def log_experiment_start(
        self,
        agent_name: str,
        experiment_id: str,
        description: str = "",
    ) -> None:
        """실험 시작 이벤트를 기록합니다."""
        event = self._create_event(
            EventType.EXPERIMENT_START,
            content=description or f"실험 시작: {experiment_id}",
            agent_name=agent_name,
            metadata={"experiment_id": experiment_id},
        )
        self._write_event(event)
        self._format_console(event)

    def log_experiment_result(
        self,
        agent_name: str,
        experiment_id: str,
        metrics: dict[str, Any],
        summary: str = "",
    ) -> None:
        """실험 결과를 기록합니다."""
        event = self._create_event(
            EventType.EXPERIMENT_RESULT,
            content=summary or f"실험 완료: {experiment_id}",
            agent_name=agent_name,
            metadata={
                "experiment_id": experiment_id,
                "metrics": metrics,
            },
        )
        self._write_event(event)
        self._format_console(event)

    def log_user_question(self, question: str) -> None:
        """사용자에게 질문을 기록합니다."""
        event = self._create_event(
            EventType.USER_QUESTION,
            content=question,
            agent_name="System",
        )
        self._write_event(event)
        self._format_console(event)

    def log_phase_complete(
        self,
        phase_number: int,
        phase_name: str,
        summary: str = "",
    ) -> None:
        """구현 단계 완료를 기록합니다."""
        event = self._create_event(
            EventType.PHASE_COMPLETE,
            content=summary or f"Phase {phase_number} 완료: {phase_name}",
            metadata={
                "phase_number": phase_number,
                "phase_name": phase_name,
            },
        )
        self._write_event(event)
        self._format_console(event)

    # ============================================================
    # 유틸리티 메서드
    # ============================================================

    def get_events(
        self,
        event_type: str | None = None,
        agent_name: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """로그 파일에서 이벤트를 읽어 반환합니다."""
        if not self._log_file.exists():
            return []

        events = []
        with open(self._log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event_type and event.get("event_type") != event_type:
                        continue
                    if agent_name and event.get("agent_name") != agent_name:
                        continue
                    events.append(event)
                except json.JSONDecodeError:
                    continue

        if limit:
            events = events[-limit:]

        return events

    def get_conversation_history(self) -> list[dict[str, Any]]:
        """에이전트 간 대화 메시지만 추출합니다."""
        return self.get_events(event_type=EventType.AGENT_MESSAGE)

    def get_experiment_results(self) -> list[dict[str, Any]]:
        """실험 결과만 추출합니다."""
        return self.get_events(event_type=EventType.EXPERIMENT_RESULT)


# ============================================================
# 글로벌 로거 인스턴스
# ============================================================

_research_logger: Optional[ResearchLogger] = None


def init_logger(
    log_dir: str = "./logs",
    session_id: str = "autogen_session",
    run_id: str | None = None,
    console_output: bool = True,
) -> ResearchLogger:
    """글로벌 연구 로거를 초기화합니다."""
    global _research_logger
    _research_logger = ResearchLogger(
        log_dir=log_dir,
        session_id=session_id,
        run_id=run_id,
        console_output=console_output,
    )
    return _research_logger


def get_logger() -> ResearchLogger:
    """글로벌 연구 로거를 반환합니다."""
    global _research_logger
    if _research_logger is None:
        _research_logger = ResearchLogger()
    return _research_logger
