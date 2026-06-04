"""Command execution and result reading tools for CrewAI agents."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

# platform/ 패키지 경로 등록 (research_system 루트)
_PLATFORM_ROOT = Path(__file__).parent.parent.parent
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

try:
    from rsp.tool_result_budget import apply_budget
except Exception:
    def apply_budget(result: str, max_chars: int = 4000) -> str:
        if len(result) <= max_chars:
            return result
        half = max_chars // 2
        trimmed = len(result) - max_chars
        return result[:half] + f"\n...[TRUNCATED {trimmed} chars]...\n" + result[-half:]


class _ArraySafeModel(BaseModel):
    """배열 입력을 data[0]으로 unwrap하는 기본 모델 (workspace 도구용)."""
    @model_validator(mode="before")
    @classmethod
    def _unwrap_array(cls, data: Any) -> Any:
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                import logging
                logging.getLogger(__name__).warning(
                    "Tool received list input; using data[0]. Full input: %s", str(data)[:200]
                )
                return dict(data[0])
            return data
        return data


class _RunInput(BaseModel):
    """RunCommandTool 전용 — 배열 입력 시 array_unwrapped=True를 세팅해 실행을 거부한다."""
    command: str = Field(description="Shell command to run (e.g. 'python src/main.py')")
    working_dir: str = Field(description="Working directory (absolute path, typically workspace_root)")
    timeout: int = Field(default=300, description="Timeout in seconds (default 300)")
    array_unwrapped: bool = Field(default=False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _detect_array(cls, data: Any) -> Any:
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                result = dict(data[0])
                result["array_unwrapped"] = True
                return result
            return data
        return data


class _ReadResultInput(_ArraySafeModel):
    result_path: str = Field(description="Absolute path to the result JSON file (e.g. workspace_root/results/result.json)")
    array_unwrapped: bool = Field(default=False, exclude=True)


class RunCommandTool(BaseTool):
    name: str = "RunCommandTool"
    description: str = (
        "Execute a shell command in a given working directory. "
        "Returns stdout, stderr, return code, and duration in seconds. "
        "Use this to run experiments (e.g. 'python src/main.py')."
    )
    args_schema: Type[BaseModel] = _RunInput

    def _run(self, command: str, working_dir: str, timeout: int = 300, array_unwrapped: bool = False) -> str:
        # 배열로 호출됐으면 명령을 실행하지 않고 즉시 거부한다.
        # Executor가 return_code를 확인할 수 있도록 -3을 반환하고 올바른 형식을 알려준다.
        if array_unwrapped:
            return json.dumps({
                "return_code": -3,
                "error": (
                    "TOOL_MISUSE: Action Input was an array -- command was NOT executed. "
                    "Retry with a single JSON object containing exactly two string fields: "
                    f'{{ "command": "{command}", "working_dir": "{working_dir}" }}'
                ),
                "tool_misuse": True,
            })

        # Normalise 'python' / 'python3' to the current interpreter so the
        # right conda env is used on Windows where 'python' is not in PATH.
        import re as _re
        _safe_exe = sys.executable.replace("\\", "/")
        command = _re.sub(r'\bpython3?\b', f'"{_safe_exe}"', command)

        start = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            duration = round(time.time() - start, 2)
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            log_dir = Path(working_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())

            # Full log for debugging (not passed to LLM)
            (log_dir / f"exec_{ts}.log").write_text(
                f"COMMAND: {command}\n"
                f"RETURN_CODE: {result.returncode}\n"
                f"DURATION_S: {duration}\n"
                f"STDOUT:\n{stdout}\n"
                f"STDERR:\n{stderr}\n",
                encoding="utf-8",
            )

            # stderr-only file — Analyzer reads this when stderr_tail is insufficient
            stderr_log = log_dir / f"exec_{ts}_stderr.log"
            stderr_log.write_text(stderr, encoding="utf-8")

            # Detect environment errors (DLL, CUDA, hardware) — not fixable by editing code
            _ENV_ERROR_MARKERS = (
                "WinError 1114",
                "DLL load failed",
                "c10.dll",
                "CUDA error",
                "libcuda",
                "libtorch",
            )
            env_error = result.returncode != 0 and any(m in stderr for m in _ENV_ERROR_MARKERS)

            payload: dict[str, Any] = {
                "return_code": result.returncode,
                "duration_s": duration,
                "stdout_tail": apply_budget(stdout, max_chars=2000),
                "stderr_tail": apply_budget(stderr, max_chars=1000),
                "stderr_log": str(stderr_log),
            }
            if env_error:
                payload["env_error"] = (
                    "ENVIRONMENT ERROR — this is NOT a code bug. "
                    "The Python runtime cannot load a native library (DLL/CUDA). "
                    "Do NOT try to fix the code. Report: environment issue, code is correct."
                )
            return json.dumps(payload, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"return_code": -1, "error": f"timeout after {timeout}s"})
        except Exception as exc:
            return json.dumps({"return_code": -1, "error": str(exc)})


class ReadResultTool(BaseTool):
    name: str = "ReadResultTool"
    description: str = (
        "Read a JSON result file produced by an experiment. "
        "Returns the parsed JSON content as a string. "
        "Use this to inspect results/result.json after running an experiment."
    )
    args_schema: Type[BaseModel] = _ReadResultInput

    def _run(self, result_path: str) -> str:
        try:
            path = Path(result_path)
            if not path.exists():
                return f"ERROR: File not found: {result_path}"
            content = path.read_text(encoding="utf-8")
            # Validate it's JSON
            json.loads(content)
            return content
        except json.JSONDecodeError as exc:
            return f"ERROR: Invalid JSON in {result_path}: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"
