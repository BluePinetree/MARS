# ADR-001 — Direct LLM Calls for Code Generation

**Date:** 2026-05-21  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase2_coding.py`

---

## Context

Phase 2 of the MARS pipeline is responsible for generating Python experiment files
(data loaders, models, trainers, entry points) and writing them to disk inside the
isolated workspace directory. The original implementation used a standard CrewAI
agent equipped with a `WorkspaceWriteTool`:

```
FileCoder agent
  └── WorkspaceWriteTool (tool)
        └── writes file content → disk
```

The expectation was that the LLM would call `WorkspaceWriteTool` with the generated
file content as the argument, and the tool would persist the file. This pattern
follows the conventional CrewAI tool-calling workflow.

---

## Problem

In practice, the LLM (Claude Sonnet via CrewAI 1.x native function-calling mode)
**returned Python code as plain text in the response body** instead of emitting a
tool call. The ReAct loop recorded the text as a "Final Answer" and moved on.
`WorkspaceWriteTool` was never invoked. The workspace remained empty.

Attempted mitigations (all partial at best):

| Mitigation | Outcome |
|---|---|
| Stronger system prompt ("MUST call the tool") | LLM complied ~60 % of the time |
| `parallel_tool_calls=False` | No measurable improvement |
| `max_iter` increase | More loops, same failure rate |
| JSON schema in task description | LLM occasionally embedded JSON *inside* prose |
| Prompt restructured as "Action / Action Input" | Improved to ~80 %, still non-deterministic |

The root problem is **architectural**: whether the tool is called depends on the LLM's
willingness at inference time. There is no guarantee in the CrewAI 1.x native
function-calling path that a tool will be invoked, especially when the LLM has been
trained to produce helpful text responses.

---

## Decision

**Remove CrewAI agents from the code-generation inner loop entirely.**

Replace the agent–tool pattern with a two-step Python procedure:

1. Call the LLM *directly* (`llm.call([system_msg, user_msg])`) and receive the file
   content as a plain string.
2. Python writes the string to disk with `pathlib.Path.write_text()`.

```python
# phase2_coding.py — simplified illustration
raw = llm.call([system_msg, user_msg])
content = _strip_fences(raw)           # remove ```python ... ``` wrappers
workspace_path.write_text(content)     # guaranteed write
```

The same pattern applies to the repair loop: current broken file + error message
are injected into the prompt, the LLM returns corrected code, Python writes it.

CrewAI `Agent`, `Crew`, and `Task` objects are still used in other phases
(planning, paper writing) where the output *is* a message, not a file.

---

## Consequences

**Positive**

- **100 % file-write reliability.** The guarantee is structural — Python always
  executes the write after the LLM returns. It cannot regress without a code change.
- **Simpler debugging.** The failure surface shrinks from
  `LLM → tool-call compliance → tool logic → disk` to `LLM → disk`.
- **Full control over prompt content.** No CrewAI task-description translation layer
  sits between the developer and the LLM.
- **Repair loop is clean.** The same `_repair_content()` function handles any
  syntax/import error by including the current broken code and the error traceback
  in the next call.

**Negative / Trade-offs**

- **Loses CrewAI's memory and inter-task context sharing** for Phase 2.
  Mitigated: each file's dependencies are read from disk and injected into the prompt
  explicitly (the actual exported symbols of already-written files), which is more
  precise than implicit agent memory.
- **More prompt engineering responsibility.** We own the full prompt; CrewAI's
  role/backstory/goal abstractions no longer apply for Phase 2.
- **Harder to swap LLM providers.** The call is made through `create_llm_for_agent()`
  (our thin factory), so provider changes require updating that factory, not just
  the agent config.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| Force `tool_choice=required` at API level | CrewAI 1.x does not expose this parameter cleanly for all providers |
| Pre-flight check + auto-repair with tool | Repair via tool has the same compliance problem |
| Switch to OpenAI function-calling strict mode | Vendor lock-in; Anthropic API has no equivalent strict-mode guarantee |
| Custom LLM wrapper that intercepts response | Too fragile; depends on response format staying consistent |

---

## Related

- [DEVLOG 2026-05-21](../DEVLOG.md#2026-05-21-architecture-decision-drop-crewai-tool-calling-switch-to-direct-llm-calls) — narrative account of the investigation
- `crewai_prototype/phases/phase2_coding.py` — `_generate_content()`, `_repair_content()`, `_write_to_disk()`
- `crewai_prototype/CLAUDE.md` — "Coder — 직접 LLM 호출 방식"
