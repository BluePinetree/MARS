# ADR-011 — Phase 3 Analyzer: Separate stderr/stdout Context Instead of Aggregated Dump

**Date:** 2026-06-03  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase3_execution.py` — `_ANALYZE_TASK` template

---

## Context

Phase 3's repair loop runs an `AnalyzerAgent` when the experiment script fails.
The analyzer reads the execution output, identifies the root cause, and produces
structured `fix_instructions` for a repair coder. The quality of the diagnosis
directly determines whether the repair loop converges.

The `_ANALYZE_TASK` template receives the execution output from `_run_script()`,
which returns a dict with keys: `return_code`, `stdout_tail`, `stderr_tail`,
`duration_s`, and optionally `result_json`.

---

## Problem

The original `_ANALYZE_TASK` template was fed the execution result via:

```python
"exec_output": json.dumps(run_result)[:2000]
```

`json.dumps(run_result)` serialises the entire result dict, including
`stdout_tail` (up to 2000 chars of training log). On a typical experiment run,
`stdout_tail` alone consumes the entire 2000-character budget, leaving zero
characters for `stderr_tail`.

**Observed failure** (run `f9149d82f1f6`):

- Actual error in stderr:
  ```
  TypeError: run_experiment_suite() got an unexpected keyword argument 'seeds'
  ```
- Analyzer output (3 consecutive repair attempts):
  ```
  "failure_diagnosis": "The traceback is truncated and does not show the root cause..."
  "fix_instructions": ["Check that all function signatures match their callers", ...]
  ```

The repair coder received vague, generic instructions. It attempted to fix
unrelated files without touching the signature mismatch. After 3 attempts the
gate escalated to the user — a problem that would have been a one-line fix if
the Analyzer had seen the actual exception.

**Root cause chain:**

1. `json.dumps(run_result)` serialises fields in dict insertion order.
2. `stdout_tail` is inserted before `stderr_tail` in `_run_script()`'s result dict.
3. A typical experiment prints 1500–2000 chars of training progress to stdout.
4. `[:2000]` truncation cuts off before the JSON structure even reaches `stderr_tail`.
5. The Analyzer receives no stack trace and cannot diagnose the failure.

This is a *silent reliability killer*: the repair loop runs, consumes LLM
budget, and makes no progress. The user sees repeated "Analyzing..." messages
with no resolution.

---

## Decision

**Pass `return_code`, `stderr_tail`, and `stdout_tail` as separate named template
variables, with independent truncation budgets sized to their diagnostic value.**

```python
_ANALYZE_TASK = """\
Execution failed. Details:

return_code: {return_code}

stderr (last 1500 chars):
{stderr_tail}

stdout (last 500 chars):
{stdout_tail}

Workspace root: {workspace_root}
...
"""

analyze_task = Task(
    description=_ANALYZE_TASK.format(
        return_code=run_result["return_code"],
        stderr_tail=run_result.get("stderr_tail", "")[-1500:],
        stdout_tail=run_result.get("stdout_tail", "")[-500:],
        workspace_root=workspace_root,
    ),
    ...
)
```

**Budget rationale:**

| Field | Budget | Reason |
|-------|--------|--------|
| `stderr_tail` | 1500 chars | The exception and traceback are always in stderr; 1500 chars captures the full traceback of all but the deepest recursive failures |
| `stdout_tail` | 500 chars | Training progress rarely helps diagnosis; 500 chars shows the last few epoch lines to confirm the script reached runtime |
| `return_code` | literal int | Always present; unambiguously distinguishes timeout (`-1`), launch failure (`-2`), and Python exception (`1`) |

---

## Consequences

**Positive**

- **Analyzer reliably sees the exception.** stderr is never crowded out by stdout.
- **Token efficiency.** Total context sent to Analyzer is bounded at ~2100 chars
  of execution output — same budget as before, but now diagnostically useful.
- **Repair loop converges faster.** Concrete fix instructions → fewer repair
  iterations → less LLM spend per failed run.

**Negative / Trade-offs**

- **stdout context is reduced.** For failures that produce no stderr (e.g.,
  a silent `sys.exit(1)` or a graceful failure caught in a broad `except`),
  the Analyzer has less context. Mitigation: if `stderr_tail` is empty and
  `return_code != 0`, the Analyzer is instructed to read relevant source files
  via `WorkspaceReadTool`.
- **Dict field order dependency removed.** The fix eliminates an implicit
  dependency on Python dict insertion order (which is guaranteed in 3.7+ but
  was not the intended mechanism here). The template is now robust to any
  reordering of `_run_script()`'s return dict.

---

## Engineering Lesson

> An aggregated context truncation that silences the error signal is a silent
> reliability killer. The repair loop runs, consumes LLM budget, and makes no
> progress — while emitting plausible-looking "Analyzing..." events that mask the
> underlying dysfunction.
>
> When constructing diagnostic prompts, always pass each signal type (error
> stream, output stream, exit code) as an independently bounded, named variable.
> Never aggregate heterogeneous signals into a single truncated string.

---

## Related

- `crewai_prototype/phases/phase3_execution.py` — `_ANALYZE_TASK`, `_run_script()`
- Run `f9149d82f1f6` — events.jsonl shows 3 consecutive "traceback truncated" diagnoses
- [ADR-008](ADR-008-repair-loop-escalation.md) — escalation behavior when repair attempts are exhausted
- [ADR-004](ADR-004-staged-code-generation.md) — how the generated code that triggered this error was produced
