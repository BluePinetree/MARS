"""
Research session orchestration for AutoGen prototype.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from autogen_agentchat.messages import TextMessage

from agents.coder import make_coder_agent, create_coder
from agents.critic import create_critic
from agents.executor import make_executor_agent, create_executor
from agents.planner import create_research_planner
from core.chat_manager import create_research_group_chat
from core.config_loader import SystemConfig, load_config
from core.local_context_store import LocalContextStore
from core.llm_factory import create_model_client, create_selector_client
from core.logger import EventType, ResearchLogger, init_logger
from core.message_bus import BusMessage, MessageBusInterface, create_message_bus
from tools.code_executor import execute_code, execute_shell_command, init_code_executor
from tools.lance_search import (
    add_knowledge,
    get_last_lancedb_query_diagnostics,
    init_knowledge_store,
    search_knowledge,
)


class ResearchConfig:
    """User input schema for one research run."""

    def __init__(
        self,
        research_topic: str,
        research_goal: str,
        research_domain: str,
        data_path: str = "",
        data_description: str = "",
        max_experiments: int = 3,
        time_limit_minutes: int = 60,
        preferred_frameworks: list[str] | None = None,
        output_path: str = "./outputs",
    ) -> None:
        self.research_topic = research_topic
        self.research_goal = research_goal
        self.research_domain = research_domain
        self.data_path = data_path
        self.data_description = data_description
        self.max_experiments = max_experiments
        self.time_limit_minutes = time_limit_minutes
        self.preferred_frameworks = preferred_frameworks or []
        self.output_path = output_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_topic": self.research_topic,
            "research_goal": self.research_goal,
            "research_domain": self.research_domain,
            "data_path": self.data_path,
            "data_description": self.data_description,
            "constraints": {
                "max_experiments": self.max_experiments,
                "time_limit_minutes": self.time_limit_minutes,
                "preferred_frameworks": self.preferred_frameworks,
            },
            "output_path": self.output_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchConfig":
        constraints = data.get("constraints", {})
        return cls(
            research_topic=data.get("research_topic", ""),
            research_goal=data.get("research_goal", ""),
            research_domain=data.get("research_domain", ""),
            data_path=data.get("data_path", ""),
            data_description=data.get("data_description", ""),
            max_experiments=constraints.get("max_experiments", 3),
            time_limit_minutes=constraints.get("time_limit_minutes", 60),
            preferred_frameworks=constraints.get("preferred_frameworks", []),
            output_path=data.get("output_path", "./outputs"),
        )

    def validate(self) -> list[str]:
        missing: list[str] = []
        if not self.research_topic:
            missing.append("research_topic")
        if not self.research_goal:
            missing.append("research_goal")
        if not self.research_domain:
            missing.append("research_domain")
        return missing

    def to_initial_prompt(self) -> str:
        parts = [
            "## Research Request",
            "",
            f"- Topic: {self.research_topic}",
            f"- Goal: {self.research_goal}",
            f"- Domain: {self.research_domain}",
        ]
        if self.data_path:
            parts.append(f"- Data path: {self.data_path}")
        if self.data_description:
            parts.append(f"- Data description: {self.data_description}")
        if self.preferred_frameworks:
            parts.append(f"- Preferred frameworks: {', '.join(self.preferred_frameworks)}")

        parts.extend(
            [
                "",
                "## Constraints",
                f"- Max experiments: {self.max_experiments}",
                f"- Time limit (minutes): {self.time_limit_minutes}",
                f"- Output path: {self.output_path}",
                "",
                "Run iterative cycles of planning -> coding -> execution -> critique.",
                "If execution fails, fix and retry until success or budget limit.",
                "After each execution, discuss anomalies and missing checks.",
                "Finish only when the planner emits RESEARCH_COMPLETE.",
            ]
        )
        return "\n".join(parts)


class ResearchSession:
    """Top-level controller for one AutoGen research run."""

    def __init__(
        self,
        config: SystemConfig | None = None,
        config_path: str | None = None,
    ) -> None:
        self._config = config or load_config(config_path)
        self._logger: Optional[ResearchLogger] = None
        self._research_config: Optional[ResearchConfig] = None
        self._group_chat = None
        self._agents: list[Any] = []
        self._run_id = ""
        self._output_dir: Path = Path("./outputs")
        self._is_running = False
        self._context_store: Optional[LocalContextStore] = None
        self._last_prompt_token_estimate: int = 0
        self._workspace_root: str = ""

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _init_run(self, research_config: ResearchConfig) -> None:
        self._research_config = research_config
        self._run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self._output_dir = Path(research_config.output_path) / self._run_id
        self._output_dir.mkdir(parents=True, exist_ok=True)
        (self._output_dir / "src").mkdir(exist_ok=True)
        (self._output_dir / "results").mkdir(exist_ok=True)
        (self._output_dir / "results" / "figures").mkdir(exist_ok=True)
        (self._output_dir / "logs").mkdir(exist_ok=True)

        self._workspace_root = str(self._output_dir)
        self._write_stable_files(self._workspace_root, research_config)

        self._logger = init_logger(
            log_dir=self._config.logging.log_dir,
            session_id="autogen_session",
            run_id=self._run_id,
            console_output=self._config.logging.console_output,
        )
        self._context_store = LocalContextStore(
            run_output_dir=self._output_dir,
            project_root=Path(__file__).resolve().parent.parent,
        )

    @staticmethod
    def _write_stable_files(workspace_root: str, config: "ResearchConfig") -> None:
        """Write artifacts.py and config_schema.py scaffold files for Coder to read."""
        src = Path(workspace_root) / "src"
        src.mkdir(parents=True, exist_ok=True)

        artifacts_py = '''\
"""Result saving helper used by experiment_impl.py / main.py."""
import json
from pathlib import Path

def write_result_json(metrics: dict, output_dir: str = "results"):
    Path(output_dir).mkdir(exist_ok=True)
    out = Path(output_dir) / "result.json"
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Result saved: {out}")
'''
        config_schema_py = f'''\
"""Runtime configuration — read by experiment_impl.py."""
from dataclasses import dataclass

@dataclass
class RuntimeContext:
    seed: int = 42
    epochs: int = 10
    batch_size: int = 32
    learning_rate: float = 1e-3
    data_path: str = {repr(getattr(config, "data_path", ""))}
    output_dir: str = "results"
'''
        (src / "artifacts.py").write_text(artifacts_py, encoding="utf-8")
        (src / "config_schema.py").write_text(config_schema_py, encoding="utf-8")

    def _create_agents(self) -> list[Any]:
        config = self._config

        init_knowledge_store(
            db_path=config.lancedb.db_path,
            table_name=config.lancedb.table_name,
            embedding_model=config.lancedb.embedding_model,
            top_k=config.lancedb.top_k,
            query_max_chars=config.lancedb.query_max_chars,
        )

        workspace_dir = str(self._output_dir / "workspace")
        init_code_executor(
            openhands_enabled=config.openhands.enabled,
            openhands_url=config.openhands.api_url,
            workspace_dir=workspace_dir,
            timeout=config.openhands.timeout_seconds,
        )

        planner_client = create_model_client(config, "research_planner")
        coder_client = create_model_client(config, "coder")
        critic_client = create_model_client(config, "critic")
        executor_client = create_model_client(config, "executor")

        planner = create_research_planner(
            model_client=planner_client,
            tools=[search_knowledge, add_knowledge],
        )
        coder = make_coder_agent(
            model_client=coder_client,
            workspace_root=self._workspace_root,
        )
        critic = create_critic(
            model_client=critic_client,
            tools=[],
        )
        executor = make_executor_agent(
            model_client=executor_client,
            workspace_root=self._workspace_root,
        )

        self._agents = [planner, coder, critic, executor]
        return self._agents

    def _create_group_chat(self):
        selector_client = create_selector_client(self._config)
        self._group_chat = create_research_group_chat(
            agents=self._agents,
            selector_model_client=selector_client,
            config=self._config,
        )
        return self._group_chat

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def _compact_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 80:
            return text[:max_chars]
        head = int(max_chars * 0.6)
        tail = max(max_chars - head - 24, 20)
        return f"{text[:head]}\n\n...[compacted]...\n\n{text[-tail:]}"

    def _actual_model_map(self) -> dict[str, str]:
        model_map: dict[str, str] = {}
        for agent_key, llm_cfg in self._config.agent_llm_mapping.items():
            model_map[agent_key] = f"{llm_cfg.provider}/{llm_cfg.model}"
        return model_map

    def _build_initial_prompt_with_local_context(self, research_config: ResearchConfig) -> str:
        base_prompt = research_config.to_initial_prompt()
        if not self._context_store:
            self._last_prompt_token_estimate = self._estimate_tokens(base_prompt)
            return base_prompt

        shared_memory = self._context_store.load_shared_memory(max_chars=4000)
        runtime_memory = self._context_store.load_runtime_memory(max_chars=2000)
        handoff_state = self._context_store.load_handoff_state()

        prompt = (
            f"{base_prompt}\n\n"
            f"## Local Shared Memory (CLAUDE.md excerpt)\n{shared_memory or '(empty)'}\n\n"
            f"## Local Runtime Memory (compact)\n{runtime_memory or '(empty)'}\n\n"
            f"## Handoff State (latest JSON)\n{handoff_state}\n"
        )

        char_budget = int(self._config.group_chat.context_char_budget)
        token_budget = int(self._config.group_chat.context_token_budget)
        compact_max = int(self._config.group_chat.compact_max_chars)

        original_chars = len(prompt)
        original_tokens = self._estimate_tokens(prompt)
        compacted = False

        if original_chars > char_budget or original_tokens > token_budget:
            compacted = True
            prompt = (
                f"{base_prompt}\n\n"
                f"## Local Runtime Memory (compacted)\n"
                f"{self._compact_text(runtime_memory or '', compact_max)}\n\n"
                f"## Handoff State (compacted)\n"
                f"{self._compact_text(str(handoff_state), compact_max)}\n"
            )

        compact_chars = len(prompt)
        compact_tokens = self._estimate_tokens(prompt)
        self._last_prompt_token_estimate = compact_tokens

        if compacted and self._context_store:
            self._context_store.append_compact_record(
                title="autogen_initial_prompt",
                original_chars=original_chars,
                compact_chars=compact_chars,
                note=(
                    f"budget exceeded (char_budget={char_budget}, token_budget={token_budget}) "
                    f"tokens {original_tokens}->{compact_tokens}"
                ),
            )

        return prompt

    def _classify_failure_point(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "collection.query" in msg:
            return "collection.query"
        query_diag = get_last_lancedb_query_diagnostics()
        if query_diag.get("status") == "failure":
            return "collection.query"
        return "llm_call"

    def _log_failure_diagnostics(self, exc: Exception, stage: str) -> None:
        if not self._logger:
            return
        query_diag = get_last_lancedb_query_diagnostics()
        failure_point = self._classify_failure_point(exc)
        self._logger.log_agent_message(
            "System",
            (
                f"Failure diagnostics: stage={stage}, failure_point={failure_point}, "
                f"prompt_token_count_estimate={self._last_prompt_token_estimate}, "
                f"query_length={query_diag.get('query_length')}"
            ),
            metadata={
                "stage": stage,
                "failure_point": failure_point,
                "actual_models": self._actual_model_map(),
                "prompt_token_count_estimate": self._last_prompt_token_estimate,
                "query_length": query_diag.get("query_length"),
                "query_length_capped": query_diag.get("query_length_capped"),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    def _persist_handoff(
        self,
        messages: list[dict[str, Any]],
        completion: dict[str, Any],
        status: str,
    ) -> None:
        if not self._context_store:
            return

        execution_items = self._collect_execution_summaries(messages)
        discussion_points = self._collect_discussion_points(messages)
        handoff_state = {
            "run_id": self._run_id,
            "status": status,
            "total_messages": len(messages),
            "completion": completion,
            "execution_summaries": execution_items[:8],
            "discussion_points": discussion_points[:10],
        }
        self._context_store.save_handoff_state(handoff_state)
        self._context_store.append_runtime_memory(
            title=f"Run {self._run_id}",
            content=(
                f"- status: {status}\n"
                f"- total_messages: {len(messages)}\n"
                f"- completion: {completion}\n"
                f"- execution_summaries: {execution_items[:8]}\n"
                f"- discussion_points: {discussion_points[:10]}\n"
            ),
        )

    async def run(self, research_config: ResearchConfig) -> dict[str, Any]:
        """Run session in non-streaming mode."""
        self._is_running = True
        message_bus: MessageBusInterface | None = None
        conversation_messages: list[dict[str, str]] = []

        try:
            self._init_run(research_config)
            assert self._logger is not None
            self._logger.log_system_start(research_config.to_dict())

            self._create_agents()
            self._logger.log_agent_message(
                "System",
                "Agents initialized: " + ", ".join(agent.name for agent in self._agents),
            )
            self._create_group_chat()

            message_bus = create_message_bus(self._config.rabbitmq)
            await message_bus.connect()

            initial_prompt = self._build_initial_prompt_with_local_context(research_config)
            self._logger.log_agent_message(
                "System",
                (
                    f"Prompt diagnostics: chars={len(initial_prompt)}, "
                    f"estimated_tokens={self._last_prompt_token_estimate}"
                ),
                metadata={
                    "actual_models": self._actual_model_map(),
                    "prompt_token_count_estimate": self._last_prompt_token_estimate,
                },
            )
            self._logger.log_agent_message("User", initial_prompt)

            result = await self._group_chat.run(task=TextMessage(content=initial_prompt, source="User"))

            for msg in result.messages:
                content = str(getattr(msg, "content", msg))
                source = str(getattr(msg, "source", "Unknown"))

                self._logger.log_agent_message(source, content)
                await message_bus.broadcast(
                    BusMessage(
                        sender=source,
                        content=content,
                        message_type="text",
                    )
                )
                conversation_messages.append({"agent": source, "content": content})

            completion = self._evaluate_completion(conversation_messages)
            if not completion["ready"]:
                raise RuntimeError(
                    "Completion criteria not met: "
                    f"execution_success={completion['execution_success']}, "
                    f"critic_approved={completion['critic_approved']}, "
                    f"discussion_present={completion['discussion_present']}, "
                    f"completion_keyword={completion['completion_keyword']}"
                )

            await self._save_outputs(conversation_messages, completion)
            self._persist_handoff(conversation_messages, completion, status="success")

            self._logger.log_system_end(
                status="success",
                summary=f"Completed with {len(conversation_messages)} messages.",
            )
            return {
                "run_id": self._run_id,
                "status": "success",
                "total_messages": len(conversation_messages),
                "output_dir": str(self._output_dir),
                "log_file": self._logger.log_file_path,
                "messages": conversation_messages,
                "completion": completion,
            }
        except Exception as exc:
            if self._logger:
                self._log_failure_diagnostics(exc, stage="run")
                self._logger.log_system_end(status="error", summary=f"Run failed: {exc}")
            if self._context_store:
                self._persist_handoff(
                    conversation_messages,
                    completion={
                        "ready": False,
                        "execution_success": False,
                        "critic_approved": False,
                        "discussion_present": False,
                        "completion_keyword": False,
                    },
                    status="failure",
                )
            raise
        finally:
            self._is_running = False
            if message_bus:
                try:
                    await message_bus.disconnect()
                except Exception:
                    pass

    async def run_stream(self, research_config: ResearchConfig) -> AsyncGenerator[dict[str, Any], None]:
        """Run session in streaming mode."""
        self._is_running = True

        try:
            self._init_run(research_config)
            assert self._logger is not None
            self._logger.log_system_start(research_config.to_dict())

            yield {
                "event_type": EventType.SYSTEM_START,
                "run_id": self._run_id,
                "content": "Research run started.",
            }

            self._create_agents()
            self._create_group_chat()
            yield {
                "event_type": EventType.AGENT_MESSAGE,
                "agent_name": "System",
                "content": f"Agents ready: {', '.join(agent.name for agent in self._agents)}",
            }

            initial_prompt = self._build_initial_prompt_with_local_context(research_config)
            task = TextMessage(content=initial_prompt, source="User")
            yield {
                "event_type": EventType.AGENT_MESSAGE,
                "agent_name": "User",
                "content": initial_prompt,
            }

            messages: list[dict[str, str]] = []
            async for msg in self._group_chat.run_stream(task=task):
                if not (hasattr(msg, "content") and hasattr(msg, "source")):
                    continue
                content = str(msg.content)
                source = str(msg.source)

                self._logger.log_agent_message(source, content)
                messages.append({"agent": source, "content": content})

                if "```python" in content:
                    match = re.search(r"```python\s*\n(.*?)```", content, re.DOTALL)
                    if match:
                        self._logger.log_code_block(source, match.group(1), language="python")

                yield {
                    "event_type": EventType.AGENT_MESSAGE,
                    "agent_name": source,
                    "content": content,
                    "message_number": len(messages),
                }

            completion = self._evaluate_completion(messages)
            if completion["ready"]:
                await self._save_outputs(messages, completion)
                self._persist_handoff(messages, completion, status="success")
                self._logger.log_system_end(
                    status="success",
                    summary=f"Completed with {len(messages)} messages.",
                )
                yield {
                    "event_type": EventType.SYSTEM_END,
                    "run_id": self._run_id,
                    "content": "Research completed.",
                    "status": "success",
                    "completion": completion,
                }
            else:
                raise RuntimeError(
                    "Completion criteria not met in stream mode: "
                    f"{completion}"
                )
        except Exception as exc:
            if self._logger:
                self._log_failure_diagnostics(exc, stage="run_stream")
                self._logger.log_system_end(status="error", summary=str(exc))
            if self._context_store:
                self._persist_handoff(
                    messages if "messages" in locals() else [],
                    completion={
                        "ready": False,
                        "execution_success": False,
                        "critic_approved": False,
                        "discussion_present": False,
                        "completion_keyword": False,
                    },
                    status="failure",
                )
            yield {
                "event_type": EventType.SYSTEM_END,
                "run_id": self._run_id,
                "content": f"Run failed: {exc}",
                "status": "error",
            }
        finally:
            self._is_running = False

    def _evaluate_completion(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Evaluate whether loop requirements were met before final report.

        execution_success: results/result.json existence (not message parsing).
        """
        # 1. execution_success: actual file existence
        result_json = Path(self._workspace_root) / "results" / "result.json" if self._workspace_root else None
        execution_success = result_json.exists() if result_json else False

        critic_approved = False
        discussion_present = False
        completion_keyword = False

        for msg in messages:
            agent = msg.get("agent", "")
            content = str(msg.get("content", ""))
            upper = content.upper()
            lower = content.lower()

            if agent == "Critic" and "APPROVED" in upper:
                critic_approved = True

            if agent in {"Critic", "ResearchPlanner"} and any(
                token in lower
                for token in [
                    "discussion",
                    "anomaly",
                    "risk",
                    "missing",
                    "check",
                    "누락",
                    "이상",
                    "검증",
                    "리스크",
                ]
            ):
                discussion_present = True

            if "RESEARCH_COMPLETE" in upper:
                completion_keyword = True

        # discussion_present fallback: at least 10 messages means discussion occurred
        if not discussion_present and len(messages) >= 10:
            discussion_present = True

        ready = execution_success and critic_approved and completion_keyword
        return {
            "ready": ready,
            "execution_success": execution_success,
            "critic_approved": critic_approved,
            "discussion_present": discussion_present,
            "completion_keyword": completion_keyword,
        }

    def _collect_execution_summaries(self, messages: list[dict[str, Any]]) -> list[str]:
        summaries: list[str] = []
        for msg in messages:
            if msg.get("agent") != "Executor":
                continue
            content = str(msg.get("content", ""))
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if lines:
                summaries.append(" | ".join(lines[:6]))
        return summaries[-10:]

    def _collect_discussion_points(self, messages: list[dict[str, Any]]) -> list[str]:
        points: list[str] = []
        for msg in messages:
            if msg.get("agent") not in {"Critic", "ResearchPlanner"}:
                continue
            for raw_line in str(msg.get("content", "")).splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if re.match(r"^([-*]|\d+\.)\s+", line):
                    lowered = line.lower()
                    if any(
                        token in lowered
                        for token in [
                            "anomaly",
                            "risk",
                            "missing",
                            "check",
                            "discussion",
                            "누락",
                            "이상",
                            "리스크",
                            "검증",
                        ]
                    ):
                        points.append(re.sub(r"^([-*]|\d+\.)\s+", "", line).strip())

        if points:
            return points[:15]

        for msg in messages:
            if msg.get("agent") in {"Critic", "ResearchPlanner"}:
                content = str(msg.get("content", ""))
                lowered = content.lower()
                if any(token in lowered for token in ["discussion", "risk", "missing", "anomaly", "검증"]):
                    points.append(content[:200].strip())
            if len(points) >= 5:
                break
        return points[:15]

    async def _save_outputs(
        self,
        messages: list[dict[str, Any]],
        completion: dict[str, Any] | None = None,
    ) -> None:
        """Save markdown report and extracted code artifacts."""
        if not self._output_dir or not self._research_config:
            return

        completion = completion or self._evaluate_completion(messages)
        execution_items = self._collect_execution_summaries(messages)
        discussion_points = self._collect_discussion_points(messages)

        report_path = self._output_dir / "report.md"
        report_lines = [
            "# Research Report",
            "",
            f"**Run ID**: {self._run_id}",
            f"**Topic**: {self._research_config.research_topic}",
            f"**Goal**: {self._research_config.research_goal}",
            f"**Domain**: {self._research_config.research_domain}",
            f"**Total Messages**: {len(messages)}",
            "",
            "## 1. Completion Gate",
            f"- execution_success: {completion['execution_success']}",
            f"- critic_approved: {completion['critic_approved']}",
            f"- discussion_present: {completion['discussion_present']}",
            f"- completion_keyword(RESEARCH_COMPLETE): {completion['completion_keyword']}",
            "",
            "## 2. Execution Summaries",
        ]

        if execution_items:
            report_lines.extend([f"- {item}" for item in execution_items])
        else:
            report_lines.append("- No executor summaries found.")

        report_lines.extend(["", "## 3. Discussion / Missing Checks"])
        if discussion_points:
            report_lines.extend([f"- {item}" for item in discussion_points])
        else:
            report_lines.append("- No explicit discussion points were found.")

        report_lines.extend(["", "## 4. Full Conversation", ""])
        for msg in messages:
            agent = msg.get("agent", "Unknown")
            content = str(msg.get("content", ""))
            report_lines.append(f"### [{agent}]")
            report_lines.append("")
            report_lines.append(content)
            report_lines.append("")
            report_lines.append("---")
            report_lines.append("")

        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        # Coder now writes files via workspace_write — no code block extraction needed.
        # Save conversation log to workspace_root/logs/ for debugging.
        if self._workspace_root:
            import json as _json
            logs_dir = Path(self._workspace_root) / "logs"
            logs_dir.mkdir(exist_ok=True)
            conversation_path = logs_dir / "conversation.jsonl"
            with conversation_path.open("w", encoding="utf-8") as f:
                for msg in messages:
                    f.write(_json.dumps(msg, ensure_ascii=False) + "\n")

        if self._logger:
            self._logger.log_file_created("System", str(report_path), "Saved structured research report.")
