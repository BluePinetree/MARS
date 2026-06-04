# ADR-008 — Three-Tier Repair Loop Escalation: Auto → Human → Stub

**Date:** 2026-05-21  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase2_coding.py`, `crewai_prototype/pipeline_config/constants.py`

---

## Context

After each file is generated in Phase 2, it undergoes syntax and import checks.
Generated code is imperfect — the LLM may produce a syntax error, a wrong import
path, or an incompatible function signature. The system needs a strategy for
handling these failures without either:
- Halting the entire pipeline on a single bad file, or
- Silently continuing with broken code that fails at execution time (Phase 3)

---

## Problem

Three naive strategies all have unacceptable failure modes:

| Strategy | Failure mode |
|----------|-------------|
| **Fail immediately** | One syntax error in one file halts a 60-minute run |
| **Infinite retry** | A file with a structural problem (missing library, impossible import) spins forever |
| **Skip all failures** | Broken files produce runtime errors in Phase 3, with no useful diagnostic |

The fundamental constraint is that the pipeline must be **reliable** (complete a
high fraction of runs end-to-end) while remaining **correct** (not silently produce
broken experiments). These goals are in tension.

---

## Decision

**Implement a three-tier escalation pattern: automated repair → human guidance →
minimal stub.**

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: Automated LLM Repair (up to N attempts)        │
│  LLM sees: broken file + error message → produces fix   │
│  On success: FILE_FIXED event, continue                 │
│  On N failures: escalate to Tier 2                      │
└────────────────────────┬────────────────────────────────┘
                         │ (N = MAX_AUTO_REPAIR_ATTEMPTS = 5)
┌────────────────────────▼────────────────────────────────┐
│  Tier 2: Human Guidance Gate                            │
│  USER_GUIDANCE_NEEDED event → GuidanceDrawer popup      │
│  User options: continue | provide_fix | skip | manual   │
│  On "provide_fix": inject hint into Tier 1, reset count  │
│  On "skip": proceed to Tier 3                           │
│  On timeout: reset count, continue Tier 1               │
└────────────────────────┬────────────────────────────────┘
                         │ (user action = "skip")
┌────────────────────────▼────────────────────────────────┐
│  Tier 3: Minimal Stub                                   │
│  Write a syntactically valid placeholder file           │
│  Pipeline continues; experiment will likely fail later  │
│  But Phase 2 completes, and Phase 3 failure is isolated  │
└─────────────────────────────────────────────────────────┘
```

**Tier 1 (Auto Repair):** The repair prompt changes strategy based on attempt
number. Attempt ≤1: include the broken code ("here's what's wrong, fix it").
Attempt ≥2: discard the broken code and regenerate from scratch ("rewrite from
scratch based on the error"). This prevents the LLM from anchoring on broken
patterns.

**Tier 3 (Stub):**

```python
def _write_stub(file_path, workspace_root, responsibility):
    stub = f'"""STUB: {file_path} — {responsibility}\nSkipped during generation."""\n# TODO: implement'
    Path(workspace_root, file_path).write_text(stub)
```

The stub is syntactically valid Python (passes the syntax check) and imports
nothing (passes the import check). Phase 2 completes successfully; Phase 3 will
fail at the point where the stub's unimplemented functionality is called. This
failure is diagnostic — the error message points to the specific stub.

**Configurable thresholds** (all readable from environment variables):

```python
MAX_AUTO_REPAIR_ATTEMPTS = 5       # Tier 1 → 2 threshold
USER_GUIDANCE_TIMEOUT_SECS = 7200  # Tier 2 → auto-reset timeout
MAX_SMOKE_TOTAL_SECS = 300         # Total wall-clock limit for smoke test repair
```

---

## Consequences

**Positive**

- **Pipeline completion rate.** Tier 3 ensures Phase 2 always terminates with a
  syntactically valid workspace, even if some files are stubs. E2E completion rate
  is higher than "fail on first error."
- **Failure isolation.** A stub in `src/models.py` produces a clear
  `AttributeError: module has no attribute 'ResNet18'` in Phase 3, pointing
  directly at the problem. This is more actionable than a cryptic Phase 2 abort.
- **Human intelligence in the loop.** Tier 2 surfaces the exact error to the user.
  A domain expert can provide a one-line hint ("use timm.create_model instead of
  torchvision") that resolves a problem no amount of automated repair could fix.
- **Attempt counter strategy shift.** Attempt ≥2 discards the broken code and
  regenerates from scratch. This avoids the "anchor bias" failure where the LLM
  keeps making the same structural mistake because it's anchored to its previous
  output.

**Negative / Trade-offs**

- **Phase 3 can fail on stub.** If a stubbed file is critical (e.g., the data
  loader), Phase 3 fails. The user must then re-run with guidance. The
  alternative — blocking Phase 2 indefinitely — is worse.
- **Guidance timeout resets counter.** If the user doesn't respond within
  `USER_GUIDANCE_TIMEOUT_SECS`, the attempt counter resets to 0 and Tier 1 retries.
  This can produce a soft loop. Acceptable: the timeout is 2 hours; a user who
  is actively monitoring will respond.
- **N=5 is arbitrary.** The `MAX_AUTO_REPAIR_ATTEMPTS` threshold was chosen
  empirically. Too low (N=1): wastes human attention on fixable errors. Too high
  (N=20): costs many LLM calls on truly broken specs. N=5 was found to resolve
  ~85% of errors automatically in early testing.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Fail immediately on any check failure** | Single file error stops 60-min run; unacceptable for research use |
| **Infinite automated retry** | Endless loop on structural errors (missing library, impossible import spec) |
| **Human guidance only (no auto-repair)** | Every minor syntax error requires human attention; too disruptive |
| **Auto-skip without human option** | Loses domain expertise; user may know the fix |
| **Full file regeneration on every failure** | Ignores the error message — regeneration with no context often reproduces the same error |

---

## Related

- [ADR-001](ADR-001-direct-llm-calls.md) — Direct LLM calls make Tier 1 repair clean: current broken code + error → LLM → fixed code → disk
- [ADR-005](ADR-005-hitl-gate-architecture.md) — GuidanceGate implements the Tier 2 blocking mechanism
- [ADR-006](ADR-006-event-taxonomy.md) — `FILE_SYNTAX_ERROR`, `FILE_FIXED`, `USER_GUIDANCE_NEEDED` events communicate tier transitions to the UI
- `crewai_prototype/phases/phase2_coding.py` — `_repair_loop()`, `_write_stub()`
- `crewai_prototype/pipeline_config/constants.py` — `MAX_AUTO_REPAIR_ATTEMPTS`, `USER_GUIDANCE_TIMEOUT_SECS`
