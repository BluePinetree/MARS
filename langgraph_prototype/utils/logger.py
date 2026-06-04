"""
표준 JSONL 로거.

'자율 연구 시스템 공통 사양 (Common Specification)' §2에 정의된
표준 로그 이벤트 형식을 준수하여 모든 에이전트 활동을 기록합니다.

지원하는 이벤트 유형 (event_type):
- SYSTEM_START    : 시스템 실행 시작
- SYSTEM_END      : 시스템 실행 종료 (성공/실패)
- AGENT_THINKING  : 에이전트 내부 사고 과정
- AGENT_MESSAGE   : 에이전트 간 공식 대화 메시지
- TOOL_CALL       : 외부 도구 호출 시작
- TOOL_RESULT     : 외부 도구 호출 결과
- FILE_CREATED    : 파일 생성 이벤트
- CODE_BLOCK      : 생성된 코드 블록
- EXPERIMENT_START  : 실험 코드 실행 시작
- EXPERIMENT_RESULT : 실험 완료 및 결과
- USER_QUESTION   : 사용자에게 질문/확인 요청
- PHASE_COMPLETE  : 구현 단계(Phase) 완료

로그 파일은 JSONL(JSON Lines) 형식이며, 통합 UI에서
채팅 형식으로 시각화됩니다.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 에이전트 색상 코드 (공통 사양 §5)
AGENT_COLORS = {
    "Research Planner":     {"color": "#1E40AF", "bg": "#DBEAFE"},
    "Experiment Designer":  {"color": "#7C3AED", "bg": "#EDE9FE"},
    "Code Generator":       {"color": "#065F46", "bg": "#D1FAE5"},
    "Experiment Executor":  {"color": "#92400E", "bg": "#FEF3C7"},
    "Result Analyzer":      {"color": "#0F766E", "bg": "#CCFBF1"},
    "Paper Writer":         {"color": "#9F1239", "bg": "#FFE4E6"},
    "Critic":               {"color": "#DC2626", "bg": "#FEE2E2"},
    "System":               {"color": "#374151", "bg": "#F3F4F6"},
}


class ResearchLogger:
    """
    표준 JSONL 로거.

    공통 사양의 로그 이벤트 형식을 준수하며,
    파일과 콘솔에 동시에 로그를 출력합니다.
    """

    def __init__(
        self,
        session_id: str,
        run_id: str,
        log_path: Optional[str] = None,
        console_output: bool = True,
    ):
        """
        로거를 초기화합니다.

        Args:
            session_id: 세션 ID.
            run_id: 실행 ID.
            log_path: JSONL 로그 파일 경로. None이면 자동 생성.
            console_output: 콘솔 출력 여부.
        """
        self.session_id = session_id
        self.run_id = run_id
        self.console_output = console_output
        self._event_count = 0

        # 로그 파일 경로 설정
        if log_path:
            self.log_path = Path(log_path)
        else:
            self.log_path = Path(f"./logs/{session_id}/{run_id}.jsonl")

        # 로그 디렉토리 생성
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # 로그 파일 핸들 (append 모드)
        self._file = open(self.log_path, "a", encoding="utf-8")

    def _emit(
        self,
        event_type: str,
        content: str = "",
        agent_name: str = "System",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        로그 이벤트를 기록합니다.

        Args:
            event_type: 이벤트 유형 (공통 사양 §2.1).
            content: 이벤트 내용.
            agent_name: 에이전트 이름.
            metadata: 추가 메타데이터.
        """
        self._event_count += 1

        event = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "session_id": self.session_id,
            "run_id": self.run_id,
            "event_type": event_type,
            "agent_name": agent_name,
            "content": content,
            "metadata": metadata or {},
        }

        # JSONL 파일에 기록
        try:
            self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._file.flush()
        except Exception as e:
            logger.error(f"로그 파일 기록 실패: {e}")

        # 콘솔 출력
        if self.console_output:
            self._print_console(event)

    def _print_console(self, event: Dict):
        """이벤트를 콘솔에 포맷하여 출력합니다."""
        event_type = event["event_type"]
        agent = event["agent_name"]
        content = event["content"]
        meta = event.get("metadata", {})

        # 이벤트 유형별 아이콘
        icons = {
            "SYSTEM_START":      "🚀",
            "SYSTEM_END":        "🏁",
            "AGENT_THINKING":    "💭",
            "AGENT_MESSAGE":     "💬",
            "TOOL_CALL":         "🔧",
            "TOOL_RESULT":       "📋",
            "FILE_CREATED":      "📄",
            "CODE_BLOCK":        "💻",
            "EXPERIMENT_START":  "🧪",
            "EXPERIMENT_RESULT": "📊",
            "USER_QUESTION":     "❓",
            "PHASE_COMPLETE":    "✅",
        }
        icon = icons.get(event_type, "📝")

        # 포맷
        ts = event["timestamp"][11:19]  # HH:MM:SS

        if event_type in ("SYSTEM_START", "SYSTEM_END"):
            print(f"\n{'='*60}")
            print(f"  {icon} [{ts}] {content}")
            print(f"{'='*60}")
        elif event_type == "AGENT_THINKING":
            print(f"  {icon} [{ts}] [{agent}] (생각) {content[:120]}{'...' if len(content) > 120 else ''}")
        elif event_type == "AGENT_MESSAGE":
            print(f"  {icon} [{ts}] [{agent}] {content[:200]}{'...' if len(content) > 200 else ''}")
        elif event_type == "TOOL_CALL":
            tool_name = meta.get("tool_name", "unknown")
            print(f"  {icon} [{ts}] [{agent}] → {tool_name} 호출")
        elif event_type == "TOOL_RESULT":
            success = "성공" if meta.get("success") else "실패"
            print(f"  {icon} [{ts}] [{agent}] ← 도구 결과: {success} | {content[:100]}")
        elif event_type == "FILE_CREATED":
            file_path = meta.get("file_path", "")
            print(f"  {icon} [{ts}] [{agent}] 파일 생성: {file_path}")
        elif event_type == "CODE_BLOCK":
            lang = meta.get("language", "python")
            lines = content.count("\n") + 1
            print(f"  {icon} [{ts}] [{agent}] 코드 블록 ({lang}, {lines}줄)")
        elif event_type == "EXPERIMENT_START":
            exp_id = meta.get("experiment_id", "")
            print(f"  {icon} [{ts}] [{agent}] 실험 시작: {exp_id}")
        elif event_type == "EXPERIMENT_RESULT":
            metrics = meta.get("metrics", {})
            success = meta.get("success", False)
            status = "성공" if success else "실패"
            print(f"  {icon} [{ts}] [{agent}] 실험 {status}: {metrics}")
        elif event_type == "USER_QUESTION":
            print(f"\n  {icon} [{ts}] [질문] {content}")
        elif event_type == "PHASE_COMPLETE":
            phase_num = meta.get("phase_number", "?")
            phase_name = meta.get("phase_name", "")
            print(f"  {icon} [{ts}] Phase {phase_num} 완료: {phase_name}")
        else:
            print(f"  {icon} [{ts}] [{agent}] {content[:150]}")

    # ──────────────────────────────────────────
    # 공개 API: 이벤트 유형별 로깅 메서드
    # ──────────────────────────────────────────

    def log_system_start(self, content: str = "자율 연구 시스템을 시작합니다."):
        """SYSTEM_START 이벤트를 기록합니다."""
        self._emit(
            event_type="SYSTEM_START",
            content=content,
            agent_name="System",
            metadata={"run_id": self.run_id, "session_id": self.session_id},
        )

    def log_system_end(self, content: str = "시스템 실행이 완료되었습니다.", status: str = "success"):
        """SYSTEM_END 이벤트를 기록합니다."""
        self._emit(
            event_type="SYSTEM_END",
            content=content,
            agent_name="System",
            metadata={"status": status, "total_events": self._event_count},
        )

    def log_agent_thinking(self, agent_name: str, content: str):
        """AGENT_THINKING 이벤트를 기록합니다."""
        self._emit(
            event_type="AGENT_THINKING",
            content=content,
            agent_name=agent_name,
        )

    def log_agent_message(self, agent_name: str, content: str):
        """AGENT_MESSAGE 이벤트를 기록합니다."""
        self._emit(
            event_type="AGENT_MESSAGE",
            content=content,
            agent_name=agent_name,
        )

    def log_tool_call(self, agent_name: str, tool_name: str, tool_input: Any = None):
        """TOOL_CALL 이벤트를 기록합니다."""
        self._emit(
            event_type="TOOL_CALL",
            content=f"{tool_name} 도구를 호출합니다.",
            agent_name=agent_name,
            metadata={
                "tool_name": tool_name,
                "tool_input": _safe_serialize(tool_input),
            },
        )

    def log_tool_result(self, agent_name: str, content: str, success: bool = True):
        """TOOL_RESULT 이벤트를 기록합니다."""
        self._emit(
            event_type="TOOL_RESULT",
            content=content,
            agent_name=agent_name,
            metadata={"success": success},
        )

    def log_file_created(self, agent_name: str, file_path: str):
        """FILE_CREATED 이벤트를 기록합니다."""
        self._emit(
            event_type="FILE_CREATED",
            content=f"파일이 생성되었습니다: {file_path}",
            agent_name=agent_name,
            metadata={"file_path": file_path},
        )

    def log_code_block(self, agent_name: str, code: str, language: str = "python"):
        """CODE_BLOCK 이벤트를 기록합니다."""
        self._emit(
            event_type="CODE_BLOCK",
            content=code,
            agent_name=agent_name,
            metadata={"language": language, "line_count": code.count("\n") + 1},
        )

    def log_experiment_start(self, agent_name: str, experiment_id: str):
        """EXPERIMENT_START 이벤트를 기록합니다."""
        self._emit(
            event_type="EXPERIMENT_START",
            content=f"실험 {experiment_id}을 시작합니다.",
            agent_name=agent_name,
            metadata={"experiment_id": experiment_id},
        )

    def log_experiment_result(
        self,
        agent_name: str,
        content: str,
        metrics: Dict = None,
        success: bool = True,
    ):
        """EXPERIMENT_RESULT 이벤트를 기록합니다."""
        self._emit(
            event_type="EXPERIMENT_RESULT",
            content=content,
            agent_name=agent_name,
            metadata={
                "metrics": metrics or {},
                "success": success,
            },
        )

    def log_user_question(self, content: str):
        """USER_QUESTION 이벤트를 기록합니다."""
        self._emit(
            event_type="USER_QUESTION",
            content=content,
            agent_name="System",
        )

    def log_phase_complete(self, phase_number: int, phase_name: str):
        """PHASE_COMPLETE 이벤트를 기록합니다."""
        self._emit(
            event_type="PHASE_COMPLETE",
            content=f"Phase {phase_number} ({phase_name})이 완료되었습니다.",
            agent_name="System",
            metadata={
                "phase_number": phase_number,
                "phase_name": phase_name,
            },
        )

    # ──────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────

    def get_log_path(self) -> str:
        """로그 파일 경로를 반환합니다."""
        return str(self.log_path)

    def get_event_count(self) -> int:
        """기록된 이벤트 수를 반환합니다."""
        return self._event_count

    def read_logs(self) -> list:
        """로그 파일의 모든 이벤트를 리스트로 반환합니다."""
        events = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except FileNotFoundError:
            pass
        return events

    def close(self):
        """로그 파일을 닫습니다."""
        if self._file and not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()


def _safe_serialize(obj: Any) -> Any:
    """JSON 직렬화 가능한 형태로 변환합니다."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
