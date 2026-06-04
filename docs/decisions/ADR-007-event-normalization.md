# ADR-007 — Event Type Normalization: Exact-Match-First Design

**Date:** 2026-05-28  
**Status:** Accepted  
**Context:** `crewai_prototype/runtime/models.py`

---

## Context

MARS uses a typed event bus: every pipeline event has an `event_type` string that
must match a value in the `EVENT_TYPES` tuple. Before storage, each event passes
through `normalize_event_type()`, which maps arbitrary strings to canonical types
and falls back to `AGENT_MESSAGE` for unknowns.

The event taxonomy contains two naming conventions:
- **UPPERCASE** for phase-level and interaction events: `SYSTEM_START`, `PHASE_COMPLETE`, `PLAN_AWAITING_APPROVAL`
- **lowercase** for high-frequency streaming events: `exec_stdout`, `token_budget_snapshot`, `failure_escalation`, `extension_proposals`

The lowercase convention was intentional: these events stream continuously during
Phase 3 execution and are matched by `lowercase` switch-cases in the frontend
renderer registry. Using lowercase names makes them visually distinguishable from
structural events in log analysis.

---

## Problem

The original `normalize_event_type()` uppercased all input before checking:

```python
# Original implementation — broken for lowercase event types
def normalize_event_type(raw: Any) -> str:
    normalized = str(raw).strip().upper()
    if normalized in EVENT_TYPES:       # EVENT_TYPES contains "exec_stdout"
        return normalized               # → returns "EXEC_STDOUT" (not in set!)
    return "AGENT_MESSAGE"             # ← always falls through for lowercase types
```

Since `EVENT_TYPES` stored `"exec_stdout"` (lowercase) but the lookup used
`"EXEC_STDOUT"` (uppercase), the lookup always missed. All lowercase events were
silently classified as `AGENT_MESSAGE`.

**Affected features (all broken simultaneously):**

| Feature | Event | UI component |
|---------|-------|--------------|
| Terminal streaming pane | `exec_stdout` | `TerminalPane` |
| Phase 2 progress bar | `token_budget_snapshot` | `TokenBudgetBar` |
| Token budget warning | `token_budget_warning` | `TokenBudgetBar` amber state |
| Failure escalation alert | `failure_escalation` | `FailureAlert` |
| Extension proposals sheet | `extension_proposals` | `ProposalSheet` |

All five features had been implemented and were non-trivially complete, yet none
activated. The root cause was a single two-character decision (`.upper()`) in the
normalization function.

---

## Decision

**Check for an exact string match first; fall back to a case-insensitive lookup
only when the exact match fails. Build the case-insensitive lookup map once at
module load time.**

```python
# runtime/models.py — module-level precomputation
_EVENT_TYPE_SET: frozenset[str] = frozenset(EVENT_TYPES)
_EVENT_TYPE_UPPER_MAP: dict[str, str] = {e.upper(): e for e in EVENT_TYPES}
# e.g. {"EXEC_STDOUT": "exec_stdout", "TOKEN_BUDGET_SNAPSHOT": "token_budget_snapshot", ...}

def normalize_event_type(raw: Any) -> str:
    if raw is None:
        return "AGENT_MESSAGE"
    s = str(raw).strip()
    if s in _EVENT_TYPE_SET:                    # O(1) exact match — handles lowercase
        return s
    canonical = _EVENT_TYPE_UPPER_MAP.get(s.upper())  # O(1) case-insensitive fallback
    return canonical or "AGENT_MESSAGE"
```

This handles all four cases correctly:

| Input | Exact match? | Upper map? | Output |
|-------|-------------|------------|--------|
| `"exec_stdout"` | ✅ | — | `"exec_stdout"` |
| `"EXEC_STDOUT"` | ✗ | ✅ | `"exec_stdout"` |
| `"PHASE_COMPLETE"` | ✅ | — | `"PHASE_COMPLETE"` |
| `"unknown_type"` | ✗ | ✗ | `"AGENT_MESSAGE"` |

The fix was verified with 11 test cases covering exact lowercase, exact uppercase,
case-mismatch, `None` input, empty string, and unknown types.

---

## Consequences

**Positive**

- **All five broken features activate immediately.** No frontend or pipeline changes
  were required — only the normalization function.
- **Mixed-case taxonomy is now sustainable.** New event types can use any case
  convention appropriate to their semantics. The normalization layer handles it.
- **O(1) lookup for all paths.** Both the exact-match check (`frozenset`) and the
  case-insensitive fallback (dict lookup) are O(1). The old `.upper()` + set lookup
  was also O(1) but produced wrong results.
- **Module-load precomputation.** `_EVENT_TYPE_SET` and `_EVENT_TYPE_UPPER_MAP` are
  built once at import time, not per-call.

**Negative / Trade-offs**

- **Silent fallback remains.** Unknown event types still fall through to
  `AGENT_MESSAGE` without raising an error. This makes typos in event type strings
  invisible — they produce slightly mis-categorized events rather than an exception.
  Accepted: raising on unknown types would be too fragile in a live pipeline where
  new event types are added frequently.

---

## Engineering Lesson

> A normalization function that silently coerces unrecognized input to a default
> is a "silent killer" for any downstream feature gated on the normalized value.
> The failure mode is: feature is implemented, tests pass in isolation, but the
> feature never activates in production because inputs are silently reclassified.

This failure pattern — **silent default masking missing registration** — also
appeared in:
- `_get_attr()` returning `None` instead of the default when an argparse attribute
  was set but `None` (masked `--architectures` arg handling)
- `ApprovalGate` treating `gate.action` as binary (approved vs. not) instead of
  ternary (approved / rejected / modified), silently routing rejections to re-plan

In each case, the fix was the same: **replace implicit fallback with explicit branching.**

---

## Related

- [ADR-006](ADR-006-event-taxonomy.md) — Why mixed-case event names exist in the first place
- [DEVLOG 2026-05-28](../DEVLOG.md#2026-05-28-bug-normalize_event_type-silently-drops-lowercase-event-types) — narrative of the investigation
- `crewai_prototype/runtime/models.py` — `normalize_event_type()`, `EVENT_TYPES`
