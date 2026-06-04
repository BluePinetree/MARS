"""Code Generator node — run_tool_loop 기반 실제 파일 기록."""

from __future__ import annotations

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
from workspace import (
    WorkspaceReadTool,
    WorkspaceWriteTool,
    WorkspaceListTool,
    SyntaxCheckTool,
    ImportCheckTool,
)


_CODER_SYSTEM = """\
You have real file-system tools. Use them now.

You are a Research Code Engineer. Your job is to write ALL mutable workspace files \
one file at a time using workspace_write tool.

Action 1 — workspace_read: Read src/artifacts.py and src/config_schema.py to understand the interface.
Action 2 — workspace_write: Write each mutable file (mode='write' for new, mode='append' for large files).
Action 3 — syntax_check: After each .py file, call syntax_check immediately.
Action 4 — import_check: After all files written, call import_check on src/experiment_impl.py.

Rules:
- One tool call at a time. Go directly to the next tool call — no planning text between calls.
- Never output file content as plain text — ONLY use workspace_write.
- Never use sklearn as a placeholder. Implement the exact domain from the spec.
- All files go under src/ with flat paths.
- You are done when all files exist and syntax_check returns OK for each.
"""

_CODER_REPAIR_SYSTEM = """\
You have real file-system tools. Use them now.

You are in REPAIR MODE. Some workspace files are missing or broken.

Action 1 — workspace_list: List src/ to see what exists.
Action 2 — workspace_write: Write or overwrite only the missing/broken files.
Action 3 — syntax_check: After each .py file, call syntax_check.
Action 4 — import_check: Verify src/experiment_impl.py after writing.

Rules:
- One tool call at a time. Go directly to the next tool call.
- Fix only the files listed in REPAIR_TARGETS.
- Do not rewrite files that already exist and pass syntax_check.
"""


def _build_coder_prompt(state: ResearchState, is_repair: bool = False) -> str:
    design = state.get("design", "")
    mutable_files = state.get("mutable_files", "")
    research_input = state.get("research_input", {})
    research_topic = research_input.get("research_topic", "")
    research_goal = research_input.get("research_goal", "")
    workspace_root = state.get("workspace_root", "")

    if is_repair:
        missing = state.get("missing_files", [])
        repair_targets = "\n".join(f"  - {f}" for f in missing)
        return (
            f"DOMAIN: {research_topic}\nGOAL: {research_goal}\n\n"
            f"WORKSPACE: {workspace_root}\n\n"
            f"DESIGNER SPEC:\n{design}\n\n"
            f"REPAIR_TARGETS (write only these):\n{repair_targets}\n\n"
            "Start by listing src/ with workspace_list, then write each missing file."
        )

    return (
        f"DOMAIN: {research_topic}\nGOAL: {research_goal}\n\n"
        f"WORKSPACE: {workspace_root}\n\n"
        f"DESIGNER SPEC:\n{design}\n\n"
        f"Write these files in order:\n{mutable_files}\n\n"
        "Start by reading src/artifacts.py and src/config_schema.py, "
        "then write each mutable file."
    )


def _check_missing_files(workspace_root: str, mutable_files: str) -> list[str]:
    if not workspace_root or not mutable_files:
        return []
    root = Path(workspace_root)
    missing = []
    for line in mutable_files.splitlines():
        rel = line.strip().lstrip("0123456789. ").strip()
        if rel and not (root / rel).exists():
            missing.append(rel)
    return missing


def _count_tool_events(history: list) -> tuple[int, int]:
    tool_calls = 0
    tool_errors = 0
    for m in history:
        content = m.get("content", []) if isinstance(m, dict) else []
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "tool_use":
                    tool_calls += 1
                elif block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    if isinstance(result_content, str) and result_content.startswith("ERROR"):
                        tool_errors += 1
    return tool_calls, tool_errors


def create_coder_node(client, model: str, is_repair: bool = False):
    def coder_node(state: ResearchState) -> dict:
        workspace_root = state.get("workspace_root", "")
        if not workspace_root:
            return {
                **update_phase(state, "coding_failed"),
                "code_status": "incomplete",
                "missing_files": ["workspace_root not set"],
            }

        tools = [
            WorkspaceReadTool(),
            WorkspaceWriteTool(),
            WorkspaceListTool(),
            SyntaxCheckTool(),
            ImportCheckTool(),
        ]

        system = _CODER_REPAIR_SYSTEM if is_repair else _CODER_SYSTEM
        messages = [{"role": "user", "content": _build_coder_prompt(state, is_repair)}]

        t0 = time.time()
        if _RSP_AVAILABLE:
            final_text, history = run_tool_loop(
                client, model, system, messages, tools, max_turns=40
            )
        else:
            final_text, history = "rsp not available", []
        duration_ms = (time.time() - t0) * 1000

        mutable_files = state.get("mutable_files", "")
        missing = _check_missing_files(workspace_root, mutable_files)
        code_status = "complete" if not missing else "incomplete"

        tool_calls, tool_errors = _count_tool_events(history)
        if _RSP_AVAILABLE:
            try:
                TelemetryStore.record(NodeEvent(
                    framework="langgraph",
                    node="coder_repair" if is_repair else "coder",
                    phase="exit",
                    duration_ms=duration_ms,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                ))
            except Exception:
                pass

        return {
            **update_phase(state, "coding_complete" if code_status == "complete" else "coding_incomplete"),
            "code_status": code_status,
            "missing_files": missing,
            "coder_messages": history,
        }

    return coder_node
