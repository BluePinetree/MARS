# ADR-012 — Phase 1 Approval Gate: Explicit Reject Branch (Hard Stop)

**Date:** 2026-06-03  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase1_planning.py` — approval gate post-processing

---

## Context

Phase 1 ends with a human approval gate: the system posts the research plan to
the UI (`PLAN_AWAITING_APPROVAL` event) and blocks on `gate.wait()`. The user
can take one of three actions:

| `gate.action` | Semantic |
|---------------|----------|
| `"approve"` | Plan is accepted; proceed to Phase 2 |
| `"modify"` | Plan needs revision; provide feedback and re-plan (up to `MAX_REPLAN_ROUNDS`) |
| `"reject"` | Plan is unacceptable; abort the entire run |

---

## Problem

The original gate-handling code tested only for `"approve"` and fell through to
a re-plan loop for everything else:

```python
# ORIGINAL (buggy)
if gate.action == "approve":
    break
# else: inject feedback and re-plan
hint = gate.feedback or ""
...
# unconditionally starts another planner round
```

When the user sent `"reject"`, the pipeline interpreted it as `"modify"` with
an empty hint. It started another planner round, posted a new
`PLAN_AWAITING_APPROVAL`, and waited for the user again — who had already
expressed a terminal intent.

**Observed failure** (integration test run `081a7254f975`):

- User sent `POST /api/v1/runs/{run_id}/approve` with `{"action": "reject", "feedback": "not interested"}`
- Expected: `SYSTEM_END`, `status=failed`
- Actual: another `PLAN_AWAITING_APPROVAL` event, pipeline still blocking

This violated the user's intent and wasted LLM tokens on an unwanted re-plan.
Worse, if `MAX_REPLAN_ROUNDS` was reached after repeated rejections, the system
would emit `USER_GUIDANCE_NEEDED` — asking the user why their plan kept getting
rejected.

---

## Decision

**Add an explicit `"reject"` branch before the modify path. Reject raises
`RuntimeError`, which the pipeline coordinator catches and converts to a clean
`SYSTEM_END` with `status=failed`.**

```python
# phase1_planning.py — approval gate post-processing

if gate.action == "approve":
    emit("AGENT_MESSAGE", "[Phase 1] Plan approved.", {...})
    break

if gate.action == "reject":
    reason = gate.feedback or "User rejected the plan."
    emit(
        "AGENT_MESSAGE",
        f"[Phase 1] Plan rejected by user: {reason[:200]}",
        {"action": "reject", "reason": reason},
    )
    raise RuntimeError(f"[Phase 1] Research plan rejected by user: {reason}")

# Only "modify" reaches here
hint = gate.feedback or ""
emit("AGENT_MESSAGE", f"[Phase 1] Re-planning (round {replan_round}/{MAX_REPLAN_ROUNDS})...", ...)
```

The `RuntimeError` propagates up to the pipeline coordinator
(`pipeline_coordinator.py`), which catches it, emits `SYSTEM_END` with
`status=failed`, and terminates the SSE stream cleanly.

---

## Consequences

**Positive**

- **Reject is a hard stop.** No further LLM calls, no new approval prompts.
- **Coordinator handles termination uniformly.** The `RuntimeError` path is
  already used for other fatal pipeline failures (e.g., workspace creation
  errors), so no new error-handling code is needed.
- **Explicit, testable branching.** All three actions (`approve`, `modify`,
  `reject`) have distinct code paths; each can be tested independently.

**Negative / Trade-offs**

- **No partial recovery from reject.** If the user rejects by mistake, the run
  is permanently `failed`. They must start a new run. This is acceptable because
  `reject` is an explicit terminal action — the UI presents it alongside a
  confirmation prompt.
- **`RuntimeError` as a control-flow signal.** Using exceptions for flow control
  is generally discouraged, but it is already the established pattern in this
  codebase for pipeline-fatal conditions. A `PipelineAborted` exception class
  could improve clarity but is deferred as a refactor.

---

## Engineering Lesson

> When a finite set of enumerated user actions map to qualitatively different
> outcomes (continue, revise, abort), implement each as an explicit branch.
> "Everything except the happy path" is not a safe default — it conflates
> distinct user intents and produces confusing, hard-to-debug behavior.

---

## Related

- `crewai_prototype/phases/phase1_planning.py` — approval gate block (lines 280–310)
- `crewai_prototype/pipeline_coordinator.py` — catches `RuntimeError`, emits `SYSTEM_END`
- Run `081a7254f975` — events.jsonl shows correct reject → SYSTEM_END sequence after fix
- Run `e35af9f53324` — events.jsonl shows correct modify → re-plan → approve sequence
- [ADR-005](ADR-005-hitl-gate-architecture.md) — HitL gate architecture (`threading.Event`, `GuidanceGate`)
