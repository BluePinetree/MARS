"""Command execution and result reading tools for AutoGen agents."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# rsp/ 등록
_RESEARCH_SYSTEM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RESEARCH_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_SYSTEM_ROOT))

try:
    from rsp.tool_result_budget import apply_budget
except Exception:
    def apply_budget(result: str, max_chars: int = 4000) -> str:
        if len(result) <= max_chars:
            return result
        half = max_chars // 2
        trimmed = len(result) - max_chars
        return result[:half] + f"\n...[TRUNCATED {trimmed} chars]...\n" + result[-half:]


class RunCommandTool:
    name = "run_command"
    description = (
        "Execute a shell command in a given working directory. "
        "Returns return_code, duration_s, stdout_tail, stderr_tail, stderr_log path."
    )

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "working_dir": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command", "working_dir"],
            },
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "working_dir": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["command", "working_dir"],
                },
            },
        }

    def as_autogen_callable(self, workspace_root: str):
        tool = self

        def _run_command(command: str, working_dir: str = "", timeout: int = 300) -> str:
            wd = working_dir if working_dir else workspace_root
            return tool.run(command, wd, timeout)

        _run_command.__name__ = self.name
        _run_command.__doc__ = self.description
        return _run_command

    def run(self, command: str, working_dir: str, timeout: int = 300) -> str:
        start = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = round(time.time() - start, 2)
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            log_dir = Path(working_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())

            (log_dir / f"exec_{ts}.log").write_text(
                f"COMMAND: {command}\nRETURN_CODE: {result.returncode}\n"
                f"DURATION_S: {duration}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}\n",
                encoding="utf-8",
            )
            stderr_log = log_dir / f"exec_{ts}_stderr.log"
            stderr_log.write_text(stderr, encoding="utf-8")

            return json.dumps({
                "return_code": result.returncode,
                "duration_s": duration,
                "stdout_tail": apply_budget(stdout, max_chars=2000),
                "stderr_tail": apply_budget(stderr, max_chars=1000),
                "stderr_log": str(stderr_log),
            }, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"return_code": -1, "error": f"timeout after {timeout}s"})
        except Exception as e:
            return json.dumps({"return_code": -1, "error": str(e)})


class ReadResultTool:
    name = "read_result"
    description = (
        "Read a JSON result file produced by an experiment. "
        "Returns parsed JSON content. Use after run_command succeeds."
    )

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "result_path": {"type": "string"},
                },
                "required": ["result_path"],
            },
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_path": {"type": "string"},
                    },
                    "required": ["result_path"],
                },
            },
        }

    def as_autogen_callable(self, workspace_root: str):
        tool = self

        def _read_result(result_path: str) -> str:
            return tool.run(result_path)

        _read_result.__name__ = self.name
        _read_result.__doc__ = self.description
        return _read_result

    def run(self, result_path: str) -> str:
        try:
            path = Path(result_path)
            if not path.exists():
                return f"ERROR: File not found: {result_path}"
            content = path.read_text(encoding="utf-8")
            json.loads(content)
            return content
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON: {e}"
        except Exception as e:
            return f"ERROR: {e}"
