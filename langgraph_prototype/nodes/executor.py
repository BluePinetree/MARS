"""Experiment Executor node — run_tool_loop 기반 실제 실행."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# research_system 루트 등록
_RSP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_RSP_ROOT) not in sys.path:
    sys.path.insert(0, str(_RSP_ROOT))

try:
    from rsp.tool_loop import run_tool_loop
    from rsp.telemetry import NodeEvent, TelemetryStore
    _RSP_AVAILABLE = True
except Exception:
    _RSP_AVAILABLE = False

from graph.state import ResearchState
from nodes.base import update_phase
from workspace import RunCommandTool, ReadResultTool


_EXECUTOR_SYSTEM = """\
You are an Experiment Executor. Your ONLY job is to run the experiment and report real results.

Action 1 — run_command: Call with command='python src/main.py', working_dir=<workspace_root>.
Action 2 — read_result: If return_code == 0, read results/result.json.

Rules:
- One tool call at a time. Go directly to the next tool call.
- If return_code != 0: report the error from stderr_tail. Do NOT fabricate metrics.
- NEVER invent return codes, accuracy values, or result files.
- If run_command returns no return_code, report execution_failed.
"""


def _build_executor_prompt(state: ResearchState) -> str:
    workspace_root = state.get("workspace_root", "")
    return (
        f"Run the experiment in workspace: {workspace_root}\n\n"
        f"Call run_command with:\n"
        f"  command = 'python src/main.py'\n"
        f"  working_dir = '{workspace_root}'\n\n"
        "If return_code == 0, read results/result.json with read_result."
    )


def _extract_return_code(history: list) -> int | None:
    """tool_loop 히스토리에서 run_command의 return_code 추출."""
    for msg in history:
        content = msg.get("content", []) if isinstance(msg, dict) else []
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "tool_result":
                    try:
                        data = json.loads(block.get("content", "{}"))
                        if "return_code" in data:
                            return data["return_code"]
                    except (json.JSONDecodeError, TypeError):
                        pass
            else:
                block_type = getattr(block, "type", None)
                if block_type == "tool_result":
                    block_content = getattr(block, "content", "{}")
                    try:
                        data = json.loads(
                            block_content if isinstance(block_content, str) else "{}"
                        )
                        if "return_code" in data:
                            return data["return_code"]
                    except (json.JSONDecodeError, TypeError):
                        pass
    return None


def create_executor_node(client, model: str):
    def executor_node(state: ResearchState) -> dict:
        workspace_root = state.get("workspace_root", "")
        if not workspace_root:
            return {
                **update_phase(state, "execution_failed"),
                "execution_output": "workspace_root not set",
                "latest_execution_success": False,
            }

        tools = [RunCommandTool(), ReadResultTool()]
        messages = [{"role": "user", "content": _build_executor_prompt(state)}]

        t0 = time.time()
        if _RSP_AVAILABLE:
            final_text, history = run_tool_loop(
                client, model, _EXECUTOR_SYSTEM, messages, tools, max_turns=5
            )
        else:
            final_text, history = "rsp not available", []
        duration_ms = (time.time() - t0) * 1000

        result_path = Path(workspace_root) / "results" / "result.json"
        execution_success = result_path.exists()

        return_code = _extract_return_code(history)
        if return_code is None:
            execution_success = False
            final_text = "execution_failed: RunCommandTool returned no return_code"

        tool_calls = sum(
            1 for m in history
            if isinstance(m.get("content"), list)
            and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in m["content"])
        )
        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="executor",
                    phase="exit",
                    duration_ms=duration_ms,
                    tool_calls=tool_calls,
                ))
            except Exception:
                pass

        experiment_id = f"exp_{int(time.time())}"
        result_entry = {
            "id": experiment_id,
            "experiment_id": experiment_id,
            "success": execution_success,
            "return_code": return_code,
            "output_summary": final_text[:500],
            "metrics": {},
            "logs_path": "",
            "error_message": "" if execution_success else final_text[:300],
        }
        if execution_success:
            try:
                result_entry["metrics"] = json.loads(
                    result_path.read_text(encoding="utf-8")
                )
            except Exception:
                pass

        existing_results = list(state.get("experiment_results", []))
        existing_results.append(result_entry)

        return {
            **update_phase(state, "execution_complete"),
            "execution_output": final_text,
            "latest_execution_success": execution_success,
            "experiment_results": existing_results,
            "executor_messages": history,
        }

    return executor_node
