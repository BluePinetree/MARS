# ADR-014 — Windows asyncio ProactorEventLoop: Pipeline Thread LLM Calls Block the HTTP Server

**Date:** 2026-06-04  
**Status:** Accepted (known operational constraint)  
**Context:** `crewai_prototype/entrypoints/api.py` — FastAPI + uvicorn on Windows

---

## Context

The MARS backend runs as a single-worker uvicorn process on Windows. The FastAPI
application uses asyncio with the ProactorEventLoop (Windows default since
Python 3.8). The research pipeline runs inside a thread pool executor so that
its blocking operations do not block the event loop:

```python
# pipeline_coordinator.py (conceptual)
asyncio.get_event_loop().run_in_executor(None, run_pipeline, run_id, ...)
```

Inside the pipeline thread, Phase 3's repair loop calls CrewAI's
`Crew.kickoff()`, which internally uses `litellm` for LLM API requests:

```python
# phase3_execution.py
Crew(agents=[...], tasks=[repair_task], verbose=False).kickoff()
```

---

## Problem

After multiple consecutive `Crew.kickoff()` calls (3 repair attempts × 2
agents = 6 calls), the FastAPI HTTP server becomes completely unresponsive to
new requests. TCP connections are accepted (OS-level buffer) but HTTP requests
time out. Restarting the uvicorn process restores responsiveness.

**Symptoms observed** (repeated across runs `eb1fc2753af5`):

```
# Curl / Invoke-RestMethod after Phase 3 repair agents finish:
The operation has timed out.     ← every request, indefinitely
```

**TCP port still accepts connections** (verified via `TcpClient.BeginConnect`)
but HTTP-layer processing is frozen.

**Root cause hypothesis:**

`litellm` uses an internal `httpx.AsyncClient` for API requests. When called
from inside a thread executor on Windows:

1. `litellm` or `httpx` may call `asyncio.get_event_loop()` from the thread
   context, which on Python 3.10+ creates a new `ProactorEventLoop` for the
   thread.
2. The new event loop shares underlying Windows I/O Completion Port (IOCP)
   resources with the main loop.
3. After several such calls, the IOCP handle table or internal state becomes
   inconsistent, causing the main loop's `_recv` callbacks to never fire —
   TCP data is buffered but never read at the asyncio layer.

This is a Windows-specific issue; the same code on Linux/Mac (which uses
`SelectorEventLoop`) does not exhibit this behavior.

---

## Decision

**Accept this as a known operational constraint for the Windows development
environment. Do not change the architecture at this time.**

Mitigations in place or planned:

1. **Prefer direct LLM calls over `Crew.kickoff()` in pipeline hot paths.**
   Phase 2 coding already uses direct `LLM.call()` (see
   [ADR-001](ADR-001-direct-llm-calls.md)). Phase 3's repair agent is the
   primary offender — migrating it to direct calls eliminates the
   `Crew.kickoff()` / `litellm` thread interaction.

2. **Rate-limit test polling to foreground sequential requests.** Using
   `run_in_background=true` shell commands that hammer the HTTP API during
   heavy pipeline workloads accelerates IOCP exhaustion. During testing, send
   requests sequentially and wait for each to complete before sending the next.

3. **Consider `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`
   as a stopgap.** The SelectorEventLoop on Windows avoids IOCP entirely,
   trading some I/O performance for stability. This has not been tested with
   uvicorn + the full pipeline but is worth evaluating.

4. **Production deployment should use Linux** (Docker or WSL2). The
   ProactorEventLoop issue is a development-environment concern; the target
   deployment environment is a Linux container where it does not apply.

---

## Consequences

**Positive**

- No code changes required for the documented workarounds.
- Issue is contained to the Windows development environment and does not affect
  Linux production deployments.

**Negative / Trade-offs**

- **Manual server restarts required** when running multiple repair-heavy Phase 3
  test runs in sequence on Windows.
- **Test automation is harder on Windows.** Any automated polling loop that
  sends requests during Phase 3 repair agent execution risks triggering the
  freeze. Sequential, foreground request patterns are required.
- **Root cause is unconfirmed.** The hypothesis involves Windows IOCP internals
  that are difficult to instrument without kernel debugging tools. The symptom
  is reproducible but the exact mechanism is inferred.

---

## Engineering Lesson

> When mixing `asyncio` with thread-based parallelism on Windows, every library
> that internally calls `asyncio.get_event_loop()` from a non-main thread is a
> potential IOCP resource leak. The ProactorEventLoop's IOCP integration is
> not thread-safe across multiple event loop instances. On Windows, prefer
> direct synchronous HTTP calls (e.g., `requests`, `httpx` in sync mode) from
> non-main threads rather than any async HTTP library.

---

## Related

- Runs `eb1fc2753af5`, `0910b073c843` — HTTP server froze after Phase 3 repair
  agent calls; manual server restart required after each
- `crewai_prototype/phases/phase3_execution.py` — `_make_repair_agent()`,
  `Crew.kickoff()` calls in the repair loop
- [ADR-001](ADR-001-direct-llm-calls.md) — why Phase 2 already avoids
  `Crew.kickoff()` in favor of direct LLM calls (same class of problem)
- Python issue tracker: asyncio ProactorEventLoop + threads on Windows
