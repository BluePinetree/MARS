"""orchestration/error_classifier.py — Pattern-based error classification (no LLM).

LLM 호출 없이 정규식 패턴 매칭만으로 에러를 분류한다.
OOM / TIMEOUT → GuidanceGate 직행 (repair 시도 불필요)
SYNTAX / IMPORT / RUNTIME → repair 시도
"""
from __future__ import annotations

import re
from enum import Enum


class ErrorKind(Enum):
    SYNTAX = "syntax"
    IMPORT = "import"
    RUNTIME = "runtime"
    TIMEOUT = "timeout"
    OOM = "oom"
    UNKNOWN = "unknown"


class ErrorClassifier:
    """Classifies stderr / error text into ErrorKind using regex patterns only."""

    _PATTERNS: dict[ErrorKind, list[str]] = {
        ErrorKind.OOM: [
            r"MemoryError",
            r"CUDA out of memory",
            r"Killed",
            r"Cannot allocate memory",
            r"\bOOM\b",
            r"out of memory",
        ],
        ErrorKind.TIMEOUT: [
            r"TimeoutExpired",
            r"timed out",
            r"Timeout",
            r"signal 9",
            r"SIGKILL",
        ],
        ErrorKind.SYNTAX: [
            r"SyntaxError",
            r"IndentationError",
            r"TabError",
        ],
        ErrorKind.IMPORT: [
            r"ModuleNotFoundError",
            r"ImportError",
            r"No module named",
        ],
        ErrorKind.RUNTIME: [
            r"RuntimeError",
            r"ValueError",
            r"TypeError",
            r"AttributeError",
            r"NameError",
            r"KeyError",
            r"IndexError",
            r"ZeroDivisionError",
            r"FileNotFoundError",
            r"PermissionError",
            r"AssertionError",
        ],
    }

    # 우선순위 순서: 먼저 매칭된 것이 최종 분류
    _PRIORITY = (
        ErrorKind.OOM,
        ErrorKind.TIMEOUT,
        ErrorKind.SYNTAX,
        ErrorKind.IMPORT,
        ErrorKind.RUNTIME,
    )

    def classify(self, stderr: str, return_code: int = -1) -> ErrorKind:
        """Return the ErrorKind matching stderr, in priority order."""
        for kind in self._PRIORITY:
            for pattern in self._PATTERNS[kind]:
                if re.search(pattern, stderr, re.IGNORECASE):
                    return kind
        return ErrorKind.UNKNOWN

    def should_escalate_immediately(self, kind: ErrorKind) -> bool:
        """OOM / TIMEOUT → repair 시도 없이 GuidanceGate로 바로 escalate."""
        return kind in (ErrorKind.OOM, ErrorKind.TIMEOUT)
