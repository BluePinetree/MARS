# ADR-005 — Human-in-the-Loop Gate Architecture (Blocking Thread + Registry)

**Date:** 2026-05-15  
**Status:** Accepted  
**Context:** `crewai_prototype/orchestration/approval_registry.py`, `crewai_prototype/api/routes/interaction.py`

---

## Context

MARS has five structured human-in-the-loop (HitL) touchpoints where the pipeline
must pause and wait for a human decision before proceeding:

| Gate | Phase | User Action |
|------|-------|-------------|
| Preflight Clarification | 0 | Answer ≤4 dataset/compute/metric questions |
| Plan Approval | 1 | Approve / request revision / reject the research plan |
| Coding Guidance | 2 | Provide a hint when automated repair fails |
| Execution Guidance | 3 | Diagnose and guide a stuck experiment |
| Context Injection | 3 | Send domain knowledge mid-execution |

The pipeline runs on a **background thread** (one thread per run). The HTTP API
runs on FastAPI's **async event loop**. These are two fundamentally different
execution contexts.

---

## Problem

A naive implementation would poll a shared dictionary from the pipeline thread:

```python
while True:
    if registry.has_response(run_id):
        response = registry.pop(run_id)
        break
    time.sleep(0.5)
```

This works but wastes CPU and makes the wait interval observable as latency.
More critically, it makes the *duration of the wait* opaque — there is no way to
distinguish "waiting for user" from "computing" by looking at thread state.

An async-only approach (making the pipeline itself async) would require rewriting
the entire pipeline into `async def` coroutines, incompatible with CrewAI's
synchronous agent execution model.

---

## Decision

**Each gate is a `threading.Event`-based object that blocks the pipeline thread
while the FastAPI async endpoint resolves it without blocking the event loop.**

```python
@dataclass
class ApprovalGate:
    plan_payload: dict
    _event: threading.Event = field(default_factory=threading.Event)
    action: str = "pending"
    feedback: Optional[str] = None

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)   # blocks pipeline thread

    def resolve(self, action: str, feedback: Optional[str] = None) -> None:
        self.action = action
        self.feedback = feedback
        self._event.set()                          # unblocks pipeline thread
```

The **Registry** is a thread-safe dict keyed by `run_id`. The pipeline registers
a gate before emitting the HitL event; the API layer resolves it:

```
Pipeline thread:                    FastAPI async endpoint:
  gate = ApprovalGate(plan)           resolved = registry.resolve(
  registry.register(run_id, gate)         run_id, action, feedback)
  emit("PLAN_AWAITING_APPROVAL")      → gate._event.set()
  gate.wait(timeout=3600)           ←── unblocks
  if gate.is_approved: ...
```

`threading.Event.wait()` releases the GIL while waiting, so the FastAPI event loop
(running on the same process) is not starved.

**Timeout semantics:** Every gate has a timeout. On timeout, the pipeline
auto-approves or continues with defaults — it never deadlocks.

**Three gate types, one pattern:**

| Class | Used for | `resolve()` call site |
|-------|----------|-----------------------|
| `ApprovalGate` | Plan approval | `POST /runs/{id}/approve` |
| `GuidanceGate` | Repair guidance + preflight | `POST /runs/{id}/guidance` |
| `CancellationToken` | Run cancellation | `DELETE /runs/{id}` |

`PreflightClarifier` reuses `GuidanceGate` directly — preflight questions use the
same gate mechanism and the same API endpoint as repair guidance.

---

## Consequences

**Positive**

- **Zero polling.** `threading.Event.wait()` is a kernel-level wait — no CPU
  cycles consumed during the wait period.
- **Clean separation of concerns.** The pipeline thread expresses intent
  (`gate.wait()`); the API layer resolves it. Neither needs to know about the
  other's execution model.
- **Timeout safety.** Every gate has a maximum wait time. A user who walks away
  from the approval dialog does not stall the pipeline indefinitely.
- **Composable.** New gate types need only inherit the `threading.Event` pattern.
  `PreflightClarifier` demonstrates this — it added 4 new HitL touchpoints in one
  file by reusing `GuidanceGate` with different `file_path` keys.
- **Observable state.** The API's `GET /runs/{id}/approval_status` and
  `GET /runs/{id}/guidance_status` endpoints read from the registry synchronously.
  The frontend knows exactly when a gate is active.

**Negative / Trade-offs**

- **One pipeline thread per run.** Each `threading.Event.wait()` occupies a thread.
  For 10 concurrent runs each at a HitL gate, 10 threads are blocked. Python
  threads are OS threads — memory overhead per blocked thread is ~1–8 MB.
  At expected scale (1–5 simultaneous sessions per researcher), this is acceptable.
- **No persistence across restarts.** If the server restarts while a gate is
  waiting, the gate is lost. The pipeline resumes from checkpoint, which re-runs
  Phase 1 and re-emits `PLAN_AWAITING_APPROVAL`. The user must re-approve.
- **Registry key collision.** If a run is cancelled and a new run is started with
  the same `run_id` before the old gate is cleaned up (very unlikely given UUID
  generation), the new gate would shadow the old one. Mitigated: gates are removed
  in the pipeline's `finally` block via `approval_registry.remove(run_id)`.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Polling loop in pipeline thread** | Wastes CPU; 0.5s polling interval adds observable latency to approval responses |
| **Make pipeline fully async** | Incompatible with CrewAI's synchronous agent execution (Crew.kickoff() is blocking) |
| **Redis Pub/Sub** | Adds a stateful external service; overkill for single-server deployment |
| **WebSocket for bidirectional HitL** | Adds connection management complexity; REST endpoints are simpler and already provide the needed synchrony (see [ADR-003](ADR-003-sse-streaming.md)) |
| **Database-backed gate state** | Enables persistence across restarts, but adds I/O latency to every gate resolution and requires a migration story for schema changes |

---

## Related

- [ADR-003](ADR-003-sse-streaming.md) — SSE for server → client events; HitL responses go the other direction via REST
- `crewai_prototype/orchestration/approval_registry.py` — `ApprovalGate`, `GuidanceGate`, `CancellationToken` and their registries
- `crewai_prototype/api/routes/interaction.py` — REST endpoints that resolve gates
- `crewai_prototype/orchestration/preflight_clarifier.py` — GuidanceGate reuse for preflight questions
- `crewai_prototype/pipeline_config/constants.py` — `APPROVAL_TIMEOUT_SECS`, `USER_GUIDANCE_TIMEOUT_SECS`
