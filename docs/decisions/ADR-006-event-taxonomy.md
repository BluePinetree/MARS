# ADR-006 — Phase 2 Event Taxonomy: Fine-grained Types over AGENT_MESSAGE

**Date:** 2026-06-02  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase2_coding.py`, `research_system_ui/client/src/components/LogEvents.tsx`

---

## Context

The MARS event bus carries all pipeline activity to the frontend via SSE. Events
are stored as `RunEvent` objects with an `event_type` field and rendered by
`LogEventRenderer` using a type-keyed renderer registry.

Phase 2 (staged code generation) involves a rich set of activities that produce
observable results: generating a file, detecting a syntax error, repairing a file,
and running the entry-point smoke test. Each activity has a distinct user-relevant
outcome.

---

## Problem

The original Phase 2 implementation emitted all activities as `AGENT_MESSAGE`:

```python
# Original (too coarse)
emit("AGENT_MESSAGE", f"[Coder] {file_path} written and verified.", ...)
emit("AGENT_MESSAGE", f"[Coder] Repairing {file_path} (attempt 1)...", ...)
emit("AGENT_MESSAGE", "[Phase 2] Smoke test passed.", ...)
```

This created two problems:

1. **UI cannot distinguish signal from noise.** File generation success, syntax
   errors, and repair completions are all rendered identically as grey chat
   bubbles. A user watching Phase 2 cannot tell at a glance whether the pipeline
   is generating, failing, or fixing.

2. **Frontend components cannot selectively render.** Test L3-2-1 checks for
   `FILE_GENERATED` events; L3-2-3 checks for `FILE_SYNTAX_ERROR → FILE_FIXED`
   sequences; L3-2-7 checks for `SMOKE_TEST_DONE`. With everything as
   `AGENT_MESSAGE`, these tests cannot be verified programmatically or visually.

The coarse taxonomy was a side effect of the early CrewAI-agent-based approach
where the pipeline had no direct control over what events the LLM emitted. After
switching to direct LLM calls (ADR-001), Python controls all event emission, making
a fine-grained taxonomy practical.

---

## Decision

**Introduce dedicated event types for each distinct Phase 2 outcome, and suppress
noise events from the log view via explicit `null` renderer entries.**

**New event types (Phase 2):**

| Event type | Trigger | Rendering |
|------------|---------|-----------|
| `FILE_GENERATED` | File written and all checks passed | Green compact card with stage badge |
| `FILE_SYNTAX_ERROR` | Syntax check failed | Red compact card with truncated error |
| `FILE_IMPORT_ERROR` | Import check failed | Red compact card (same renderer) |
| `FILE_FIXED` | Repair attempt succeeded | Sky-blue compact card with attempt count |
| `FILE_GENERATION_FAILED` | Generation + repair all failed | Red compact card |
| `SMOKE_TEST_DONE` | Smoke test completed (pass or fail) | Emerald / red badge card |
| `SMOKE_TEST_START` | Smoke test starting | Suppressed (null) |
| `SMOKE_TEST_SKIPPED` | Smoke test bypassed | Suppressed (null) |
| `FILE_GENERATION_START` | File generation beginning | Suppressed (null) |

**Suppression via null renderer:**

```typescript
const EVENT_RENDERERS: Record<string, EventRenderer | null> = {
  FILE_GENERATED:    ({ event }) => <FileGenerated event={event} />,
  FILE_SYNTAX_ERROR: ({ event }) => <FileError event={event} />,
  FILE_FIXED:        ({ event }) => <FileFixed event={event} />,
  SMOKE_TEST_DONE:   ({ event }) => <SmokeTestDone event={event} />,
  SMOKE_TEST_START:  null,   // stored in event log, not shown in UI
  FILE_GENERATION_START: null,
};
```

`null` means "this event is stored for replay and debugging, but the log view
should not render it." `undefined` (missing key) means "unrecognized event — fall
through to generic renderer." The distinction is intentional.

**Helper in Python to emit the right error type:**

```python
def _emit_check_error(emit, file_path, check, attempt):
    error_type = getattr(check, "error_type", "") or ""
    event_type = "FILE_IMPORT_ERROR" if error_type == "import" else "FILE_SYNTAX_ERROR"
    emit(event_type, ..., {"file_path": file_path, "error": check.error})
```

---

## Consequences

**Positive**

- **Scannable log view.** A user monitoring Phase 2 can immediately see:
  green = file generated, red = error, sky-blue = repaired, emerald = smoke test
  passed. No need to read the message text.
- **Testable pipeline behavior.** Integration tests can subscribe to the event
  stream and assert `FILE_GENERATED` appears for each designed file in stage order,
  `SMOKE_TEST_DONE` appears exactly once, and `FILE_SYNTAX_ERROR` is always
  followed by either `FILE_FIXED` or `USER_GUIDANCE_NEEDED`.
- **Analytics-ready.** Future benchmark tooling can count
  `FILE_SYNTAX_ERROR` + `FILE_IMPORT_ERROR` per run to measure "code repair
  rate" — a primary MARS benchmark metric — without parsing log text.
- **Extensible.** Adding Phase 3 execution events (`EXEC_STARTED`, `EXEC_FAILED`,
  `EXEC_RETRYING`) follows the same pattern.

**Negative / Trade-offs**

- **More event types to maintain.** Every new event type must be added to:
  `EVENT_TYPES` tuple (backend), `EventType` union (frontend), `EVENT_TYPE_CONFIG`
  (frontend filter UI), and `EVENT_RENDERERS` (frontend renderer). Four files per
  new event type.
- **`AGENT_MESSAGE` fallback still exists.** Any event emission in Phase 2 that
  doesn't call `_emit_check_error()` will silently fall through to `AGENT_MESSAGE`.
  This is acceptable for informational messages, but could mask a missing
  fine-grained emission.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Keep AGENT_MESSAGE, add a subtype field** | `metadata.subtype = "file_generated"` — requires frontend to inspect metadata for rendering; breaks the type-keyed registry pattern |
| **Dedicate one aggregate event per file** (FILE_RESULT with nested pass/fail/error) | Aggregation requires the pipeline to wait until all repair attempts complete; real-time streaming becomes impossible |
| **Only add SMOKE_TEST_DONE, keep others as AGENT_MESSAGE** | Partial solution; doesn't help with the scannable log view goal |

---

## Related

- [ADR-007](ADR-007-event-normalization.md) — Why mixed-case event names are intentional and how they are safely normalized
- `crewai_prototype/phases/phase2_coding.py` — `_emit_check_error()`, `_repair_loop()`, `_run_smoke_test()`
- `crewai_prototype/runtime/models.py` — `EVENT_TYPES` tuple, `normalize_event_type()`
- `research_system_ui/client/src/components/LogEvents.tsx` — `FileGenerated`, `FileError`, `FileFixed`, `SmokeTestDone` renderers
- `research_system_ui/client/src/lib/types.ts` — `EventType` union
