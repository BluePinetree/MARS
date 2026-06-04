"""CrewAI callback helpers owned by the V2 runtime."""

from __future__ import annotations

import re
from typing import Any

from core.logger import ResearchLogger


class CrewCallbackHandler:
    """Convert CrewAI callback payloads into structured logger events."""

    def __init__(self, logger: ResearchLogger):
        self.logger = logger
        self._current_phase = 0

    def on_step(self, step_output: Any) -> None:
        """Handle one CrewAI intermediate step."""
        try:
            agent_name = self._extract_agent_name(step_output)
            content = self._extract_content(step_output)

            if self._is_tool_call(step_output):
                tool_name = self._extract_tool_name(step_output)
                tool_input = self._extract_tool_input(step_output)
                self.logger.tool_call(agent_name, tool_name, tool_input)
                return

            if self._is_thinking(step_output):
                self.logger.agent_thinking(agent_name, content)
            else:
                self.logger.agent_message(agent_name, content)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.log("AGENT_MESSAGE", f"[callback error] {exc}", agent_name="System")

    def on_task_complete(self, task_output: Any) -> None:
        """Handle CrewAI task completion."""
        try:
            self._current_phase += 1

            description = ""
            agent_name = "System"

            if hasattr(task_output, "description"):
                description = self._summarize_task_description(str(task_output.description))
            if hasattr(task_output, "agent"):
                agent_name = getattr(task_output.agent, "role", "System")

            message = f"Task complete: {description}" if description else "Task complete."
            metadata: dict[str, Any] = {}
            output_preview = self._extract_task_output_preview(task_output)
            if output_preview:
                metadata["task_output_preview"] = output_preview

            self.logger.log(
                "AGENT_MESSAGE",
                message,
                agent_name=agent_name,
                metadata=metadata or None,
            )

            phase_names = {
                1: "Research Planning",
                2: "Experiment Design",
                3: "Code Generation",
                4: "Execution",
                5: "Analysis",
                6: "Report Writing",
            }
            phase_name = phase_names.get(self._current_phase, f"Phase {self._current_phase}")
            self.logger.phase_complete(self._current_phase, phase_name)
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.logger.log("AGENT_MESSAGE", f"[task callback error] {exc}", agent_name="System")

    @staticmethod
    def _extract_agent_name(step_output: Any) -> str:
        if hasattr(step_output, "agent"):
            agent = step_output.agent
            if hasattr(agent, "role"):
                return str(agent.role)

        text = str(step_output)
        known_agents = [
            "Research Planner",
            "Experiment Designer",
            "Code Generator",
            "Experiment Executor",
            "Result Analyzer",
            "Paper Writer",
        ]
        lower = text.lower()
        for name in known_agents:
            if name.lower() in lower:
                return name
        return "System"

    @staticmethod
    def _extract_content(step_output: Any) -> str:
        for attr in ("text", "output", "result", "raw", "content"):
            if hasattr(step_output, attr):
                value = getattr(step_output, attr)
                if value:
                    return str(value)
        return str(step_output)

    @staticmethod
    def _is_tool_call(step_output: Any) -> bool:
        if hasattr(step_output, "tool"):
            return bool(step_output.tool)
        content = str(step_output).lower()
        return "tool" in content and "call" in content

    @staticmethod
    def _extract_tool_name(step_output: Any) -> str:
        if hasattr(step_output, "tool"):
            return str(step_output.tool)

        text = str(step_output)
        lower = text.lower()
        known_tools = [
            "chromadb_search",
            "chromadb_store",
            "workspace_execute_code",
            "workspace_prepare_file",
            "e2b_execute_code",
            "e2b_upload_file",
            "mlflow_log",
            "mlflow_query",
            "file_write",
            "file_read",
        ]
        for tool_name in known_tools:
            if tool_name in lower:
                return tool_name

        match = re.search(r"tool[_\s-]*name\s*[:=]\s*([a-zA-Z0-9_\-]+)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        return "unknown_tool"

    @staticmethod
    def _extract_tool_input(step_output: Any) -> str:
        if hasattr(step_output, "tool_input"):
            return str(step_output.tool_input)
        return ""

    @staticmethod
    def _is_thinking(step_output: Any) -> bool:
        content = str(step_output).lower()
        return any(token in content for token in ("thought:", "thinking:", "i need to", "let me"))

    @staticmethod
    def _summarize_task_description(description: str, max_chars: int = 120) -> str:
        compact = re.sub(r"\s+", " ", description).strip()
        if not compact:
            return ""
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "..."

    @staticmethod
    def _extract_task_output_preview(task_output: Any, max_chars: int = 500) -> str:
        for attr in ("raw", "output", "result", "content"):
            if hasattr(task_output, attr):
                value = getattr(task_output, attr)
                if value:
                    compact = str(value).strip()
                    if not compact:
                        continue
                    if len(compact) <= max_chars:
                        return compact
                    return compact[: max_chars - 1].rstrip() + "..."
        return ""
