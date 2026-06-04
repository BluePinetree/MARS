"""
Group chat orchestration for AutoGen research workflow.
"""

from __future__ import annotations

from typing import Sequence

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import SelectorGroupChat
from autogen_core.models import ChatCompletionClient

from core.config_loader import SystemConfig

MAX_REPAIR_CYCLES = 3


def _msg_source(message) -> str:
    return str(getattr(message, "source", ""))


def _msg_content(message) -> str:
    return str(getattr(message, "content", ""))


def _has_executor_result(messages: Sequence) -> bool:
    for msg in messages:
        if _msg_source(msg) != "Executor":
            continue
        content = _msg_content(msg).lower()
        if any(
            token in content
            for token in [
                "[execution result]",
                "[execution failed]",
                "status: success",
                "status: failed",
                "status: success",   # new executor format (uppercase)
                "execution success",
                "execution failed",
                "[실행 결과]",
                "[실행 실패]",
            ]
        ):
            return True
    return False


def custom_selector_func(messages: Sequence) -> str | None:
    """Deterministic routing with Circuit Breaker for repair cycles."""
    if not messages:
        return "ResearchPlanner"

    last = messages[-1]
    source = _msg_source(last)
    content = _msg_content(last)
    upper = content.upper()
    lower = content.lower()

    # Circuit Breaker: too many NEEDS_REVISION → force Executor
    needs_revision_count = sum(
        1 for m in messages if "NEEDS_REVISION" in _msg_content(m).upper()
    )
    if needs_revision_count >= MAX_REPAIR_CYCLES:
        if not _has_executor_result(messages):
            return "Executor"

    # 1) Coder signals FILES_WRITTEN → Critic reviews.
    if source == "Coder" and "FILES_WRITTEN" in upper:
        return "Critic"

    # 2) Coder is still writing (tool calls in progress) → let it continue.
    if source == "Coder":
        return None

    # 3) Critic controls approve/revise decisions.
    if source == "Critic":
        if "NEEDS_REVISION" in upper:
            return "Coder"
        if "APPROVED" in upper:
            if not _has_executor_result(messages):
                return "Executor"
            return "ResearchPlanner"
        # No clear verdict → ask Coder to revise
        return "Coder"

    # 4) Every executor output goes to Critic for discussion/checks.
    if source == "Executor":
        return "Critic"

    # 5) Planner either asks for next coding round or ends with RESEARCH_COMPLETE.
    if source == "ResearchPlanner":
        if "RESEARCH_COMPLETE" in upper:
            return None
        return "Coder"

    # Fallback to model-based selection.
    return None


CUSTOM_SELECTOR_PROMPT = """You select the next speaker for a research team chat.

Participants:
{roles}

Hard routing requirements:
1. Coder emits FILES_WRITTEN -> Critic (review files)
2. Critic with NEEDS_REVISION -> Coder
3. Critic with APPROVED (before first execution) -> Executor
4. Executor -> Critic (discuss anomalies/missing checks)
5. Critic with APPROVED (after execution) -> ResearchPlanner
6. ResearchPlanner ends only with RESEARCH_COMPLETE; otherwise -> Coder

Conversation history:
{history}

Pick exactly one next speaker from:
{participants}
Return only the agent name.
"""


def create_research_group_chat(
    agents: list[AssistantAgent],
    selector_model_client: ChatCompletionClient,
    config: SystemConfig,
) -> SelectorGroupChat:
    """Create selector-based group chat with deterministic loop routing."""
    chat_config = config.group_chat

    termination = MaxMessageTermination(max_messages=chat_config.max_rounds) | TextMentionTermination(
        text=chat_config.termination_keyword
    )

    return SelectorGroupChat(
        participants=agents,
        model_client=selector_model_client,
        termination_condition=termination,
        max_turns=chat_config.max_rounds,
        selector_prompt=CUSTOM_SELECTOR_PROMPT,
        allow_repeated_speaker=chat_config.allow_repeat_speaker,
        selector_func=custom_selector_func,
    )
