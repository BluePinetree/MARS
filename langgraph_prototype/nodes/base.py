"""
Shared node utilities: prompt building, context compaction, diagnostics, and local handoff state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from graph.state import ResearchState
from tools.pinecone_tool import get_last_pinecone_query_diagnostics
from utils.local_context_store import LocalContextStore


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_output_dir(state: ResearchState) -> Path:
    output_base = str(state.get("research_input", {}).get("output_path", "./outputs"))
    run_id = str(state.get("run_id", "unknown_run"))
    path = Path(output_base) / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _context_store(state: ResearchState) -> LocalContextStore:
    return LocalContextStore(
        run_output_dir=_run_output_dir(state),
        project_root=_project_root(),
    )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _compact_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 80:
        return text[:max_chars]
    head = int(max_chars * 0.6)
    tail = max(max_chars - head - 24, 20)
    return f"{text[:head]}\n\n...[compacted]...\n\n{text[-tail:]}"


def _safe_model_name(llm) -> str:
    for attr in ("model_name", "model"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)

    default_params = getattr(llm, "_default_params", None)
    if isinstance(default_params, dict) and default_params.get("model"):
        return str(default_params["model"])

    return llm.__class__.__name__


def _load_latest_analysis_json(state: ResearchState) -> str:
    path = str(state.get("latest_analysis_json_path", "")).strip()
    if not path:
        handoff_path = str(state.get("handoff_state_path", "")).strip()
        if handoff_path:
            try:
                data = json.loads(Path(handoff_path).read_text(encoding="utf-8"))
                path = str(data.get("analysis_json_path", "")).strip()
            except Exception:
                path = ""

    if not path:
        return ""

    file_path = Path(path)
    if not file_path.exists():
        return ""

    try:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def get_research_context(
    state: ResearchState,
    agent_name: str = "generic",
    logger=None,
) -> str:
    """Build compact context for current node with budget guards."""
    ri = state.get("research_input", {})
    constraints = ri.get("constraints", {})

    char_budget = int(state.get("context_char_budget", 24000))
    token_budget = int(state.get("context_token_budget", 6000))
    compact_max_chars = int(state.get("compact_max_chars", 2000))

    store = _context_store(state)
    shared_memory = store.load_shared_memory(max_chars=4000)
    runtime_memory = store.load_runtime_memory(max_chars=2000)
    handoff_state = store.load_handoff_state()

    base_parts: list[str] = [
        "## Research Input",
        f"- topic: {ri.get('research_topic', 'N/A')}",
        f"- goal: {ri.get('research_goal', 'N/A')}",
        f"- domain: {ri.get('research_domain', 'N/A')}",
    ]

    if ri.get("data_path"):
        base_parts.append(f"- data_path: {ri.get('data_path')}")
    if ri.get("data_description"):
        base_parts.append(f"- data_description: {ri.get('data_description')}")
    if constraints.get("max_experiments"):
        base_parts.append(f"- max_experiments: {constraints.get('max_experiments')}")

    results = state.get("experiment_results", [])
    result_lines: list[str] = []
    if results:
        result_lines.append("## Experiment Summaries")
        for idx, item in enumerate(results[-3:], 1):
            result_lines.append(
                (
                    f"- exp{idx}: id={item.get('experiment_id')} "
                    f"success={item.get('success')} metrics={item.get('metrics', {})} "
                    f"logs_path={item.get('logs_path', '')}"
                )
            )

    sections: list[str] = ["\n".join(base_parts)]

    # Coder gets minimal iterative context: latest analysis JSON + handoff state only.
    if agent_name.lower() in {"code generator", "coder"}:
        latest_analysis_json = _load_latest_analysis_json(state)
        coder_context = [
            "## Coder Handoff",
            f"latest_analysis_json:\n{latest_analysis_json or '(empty)'}",
            f"handoff_state:\n{json.dumps(handoff_state, ensure_ascii=False, indent=2) if handoff_state else '{}'}",
        ]
        sections.append("\n\n".join(coder_context))
    else:
        if state.get("plan"):
            sections.append(f"## Plan\n{state.get('plan')}")
        if state.get("design"):
            sections.append(f"## Design\n{state.get('design')}")
        if state.get("analysis"):
            sections.append(f"## Latest Analysis Summary\n{state.get('analysis')}")
        if result_lines:
            sections.append("\n".join(result_lines))

    sections.extend(
        [
            f"## Shared Memory (CLAUDE.md excerpt)\n{shared_memory or '(empty)'}",
            f"## Runtime Memory (compact)\n{runtime_memory or '(empty)'}",
        ]
    )

    context = "\n\n".join(sections)
    original_chars = len(context)
    original_tokens = estimate_tokens(context)

    if original_chars > char_budget or original_tokens > token_budget:
        compacted_sections = [
            "\n".join(base_parts),
            f"## Handoff State (compacted)\n{_compact_text(json.dumps(handoff_state, ensure_ascii=False), compact_max_chars)}",
            f"## Runtime Memory (compacted)\n{_compact_text(runtime_memory, compact_max_chars)}",
            f"## Plan Summary (compacted)\n{_compact_text(str(state.get('plan', '')), compact_max_chars)}",
            f"## Design Summary (compacted)\n{_compact_text(str(state.get('design', '')), compact_max_chars)}",
            f"## Analysis Summary (compacted)\n{_compact_text(str(state.get('analysis', '')), compact_max_chars)}",
        ]
        context = "\n\n".join(compacted_sections)
        compact_chars = len(context)
        compact_tokens = estimate_tokens(context)

        store.append_compact_record(
            title=f"{agent_name or 'node'}_context",
            original_chars=original_chars,
            compact_chars=compact_chars,
            note=(
                f"budget exceeded (char_budget={char_budget}, token_budget={token_budget}) "
                f"tokens {original_tokens}->{compact_tokens}"
            ),
        )

        if logger:
            logger.log_agent_message(
                "System",
                (
                    f"Context compacted for {agent_name}: "
                    f"chars {original_chars}->{compact_chars}, tokens {original_tokens}->{compact_tokens}"
                ),
            )

    return context


def call_llm(
    llm,
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    logger=None,
    state: Optional[ResearchState] = None,
) -> str:
    """Invoke LLM with diagnostics logging. Supports langchain BaseChatModel (lazy import)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt_token_estimate = estimate_tokens(system_prompt) + estimate_tokens(user_prompt)
    actual_model = _safe_model_name(llm)

    if logger:
        logger.log_agent_thinking(
            agent_name,
            (
                f"LLM call start: model={actual_model}, "
                f"chars={len(user_prompt)}, prompt_tokens_estimate={prompt_token_estimate}"
            ),
        )

    start_time = time.time()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = llm.invoke(messages)
        result = str(response.content)
    except Exception as exc:
        query_diag = get_last_pinecone_query_diagnostics()
        failure_point = "llm_call"
        if "collection.query" in str(exc).lower() or query_diag.get("status") == "failure":
            failure_point = "collection.query"

        if logger:
            logger.log_agent_message(
                "System",
                (
                    f"Failure diagnostics: stage=call_llm, failure_point={failure_point}, "
                    f"actual_model={actual_model}, prompt_token_count_estimate={prompt_token_estimate}, "
                    f"error_type={type(exc).__name__}, error_message={exc}"
                ),
            )
        raise

    duration_ms = int((time.time() - start_time) * 1000)
    if logger:
        logger.log_agent_message(
            agent_name,
            f"LLM response received ({duration_ms}ms, {len(result)} chars).",
        )

    return result


def save_text_artifact(state: ResearchState, relative_path: str, content: str) -> str:
    """Save artifact text under run output directory and return absolute path."""
    run_dir = _run_output_dir(state)
    path = run_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.resolve())


def persist_handoff_state(
    state: ResearchState,
    payload: dict[str, Any],
    logger=None,
) -> str:
    """Persist compact handoff_state.json and runtime memory notes."""
    store = _context_store(state)
    store.save_handoff_state(payload)

    summary_lines = [
        f"run_id: {state.get('run_id', 'unknown')}",
        f"phase: {state.get('current_phase', 'unknown')}",
        f"payload_keys: {sorted(payload.keys())}",
    ]
    store.append_runtime_memory(
        title=f"Handoff update - {state.get('current_phase', 'unknown')}",
        content="\n".join(summary_lines),
    )

    path = str(store.handoff_state_path.resolve())
    if logger:
        logger.log_file_created("System", path)
    return path


def update_phase(state: ResearchState, phase_name: str) -> dict:
    """Return state patch for phase transition."""
    return {
        "current_phase": phase_name,
        "phase_history": [phase_name],
    }


def create_tool_loop_context(settings=None) -> tuple:
    """(anthropic_client, model_name) 반환. coder/executor 노드에서 run_tool_loop 호출 시 사용."""
    from config.llm_factory import create_anthropic_client, get_agent_model
    client = create_anthropic_client()
    model = get_agent_model(settings, "coder")
    return client, model
