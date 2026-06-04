# DEVLOG — Research System (MARS)

> **Multi-Agent Research System**: End-to-end automated research pipeline built on top of LLM agent frameworks (CrewAI, AutoGen, LangGraph), with a real-time streaming UI and human-in-the-loop approval gates.

This log documents engineering decisions, bugs, and lessons learned during active development. Written at the end of each session — not in advance.

---

## [2026-05-21] Architecture Decision: Drop CrewAI Tool Calling, Switch to Direct LLM Calls

**Context:** Phase 2 (code generation) originally used CrewAI agents with `WorkspaceWriteTool`. Files were never being written to disk.

**Root cause:** In CrewAI 1.x native function-calling mode, the LLM would return Python code as plain text in its response body instead of calling the tool. The file write never executed. Prompts, `parallel_tool_calls=False`, and other mitigations gave partial improvement but no structural guarantee.

**Decision:** Remove CrewAI agents from Phase 2 entirely. Call the LLM directly via `llm.call([...])`, receive the file content as a string, and write it to disk in Python. Tool-call compliance is no longer the LLM's responsibility.

**Result:** 100% file write reliability. The fix is structural — it cannot regress.

**Lesson:** CrewAI's agent loop is well-suited to orchestration (routing, delegation) but introduces a fragile dependency when the output must be a file, not a message. For deterministic side effects, own the I/O yourself.

---

## [2026-05-28] Bug: `normalize_event_type` Silently Drops Lowercase Event Types

**Context:** Frontend components for `exec_stdout` (terminal output), `token_budget_snapshot` (progress bar), `failure_escalation`, and `extension_proposals` were never activating.

**Root cause:** `runtime/models.py`'s `normalize_event_type()` converted input to `.upper()` before checking against `EVENT_TYPES`. Since these event types were registered with lowercase names (matching the frontend's switch-case), the uppercased version never matched — all silently fell back to `AGENT_MESSAGE`.

```python
# Before (broken)
normalized = str(raw_event_type).strip().upper()
if normalized in EVENT_TYPES:     # "EXEC_STDOUT" not in set
    return normalized
return "AGENT_MESSAGE"            # always triggered for lowercase types
```

**Fix:** Check original string first, then case-insensitive fallback. Build a `{UPPERCASE: canonical}` lookup dict at module load.

```python
# After
s = str(raw_event_type).strip()
if s in _EVENT_TYPE_SET:          # exact match (handles lowercase)
    return s
canonical = _EVENT_TYPE_UPPER_MAP.get(s.upper())  # case-insensitive
return canonical or "AGENT_MESSAGE"
```

Also added `exec_stdout`, `token_budget_snapshot`, `token_budget_warning`, `failure_escalation`, `extension_proposals` to `EVENT_TYPES`.

**Result:** Terminal pane, TokenBudgetBar, FailureAlert, ProposalSheet all activate correctly.

**Lesson:** A normalization function that silently coerces to a default is a silent killer for any feature gated on event type matching. Tested the fix with 11 cases before merging.

---

## [2026-05-29] Bug: `@dataclass` Files Always Fail Import Check

**Context:** Phase 2 smoke tests reported import failures for all files using `@dataclass`. Every `src/models.py`, `src/config.py` etc. failed the import check even with syntactically correct code.

**Root cause:** `check_import()` loaded files with `importlib.util.spec_from_file_location('_chk', path)` and called `spec.loader.exec_module(mod)` — but never registered the module in `sys.modules` first. When `@dataclass` decorator executes, it calls `sys.modules.get(cls.__module__)` to resolve forward references. With `_chk` absent from `sys.modules`, this returned `None`, causing a `TypeError` inside the decorator.

**Fix:** One line before `exec_module`:

```python
sys.modules['_chk'] = mod      # register BEFORE exec_module
spec.loader.exec_module(mod)
```

**Result:** All `@dataclass`-decorated files pass import check.

**Lesson:** `exec_module` without prior `sys.modules` registration is subtly broken for any code that inspects its own module at decoration time. This is not documented in the Python importlib docs.

---

## [2026-05-30] Bug: Phase 0 `PHASE_COMPLETE` Event Never Emitted

**Context:** The Phase stepper in the UI never showed Phase 0 as completed — it jumped straight from Phase 0 (active) to Phase 1.

**Root cause:** `pipeline_orchestrator.py` emitted `PHASE_START(0)` and then proceeded through preflight clarification but never emitted `PHASE_COMPLETE(0)`. The preflight loop returned and immediately started Phase 1.

**Fix:** Added `emit("PHASE_COMPLETE", "[Phase 0] Workspace setup complete.", {"phase": 0})` after preflight completes in `_execute()`.

---

## [2026-05-31] Feature: Token Budget Progress Bar

**Context:** `TokenBudgetBar` component existed in the UI but never appeared during Phase 2.

**Root cause (two-part):**
1. `TokenBudgetTracker` class existed but was never called — no `token_budget_snapshot` events were emitted during file generation.
2. Even after adding emission (Part 1 fix), the bar still didn't appear due to the `normalize_event_type` bug above (Part 2 — the event was being silently dropped).

**Fix:** Added per-file `token_budget_snapshot` emission in `run_coding_phase()` tracking `files_done / total_files`. Combined with the `normalize_event_type` fix, the bar now animates from 0→100% across Phase 2.

---

## [2026-06-01] Bug: Phase 3 Experiment Fails — Relative Imports in Generated Code

**Context:** After Phase 2 succeeded and smoke test passed, Phase 3 always failed with `ImportError: attempted relative import with no known parent package`.

**Root cause:** `_generate_content()` prompt had no import rules. The LLM generated files with relative imports (`from .module import X`, `from .utils import Y`). These work inside a package but fail when the script is invoked as `python src/main.py` (a top-level script, not a package context). The workspace root is on `sys.path`, making absolute imports the correct form.

**Fix:** Added explicit IMPORT RULES section to both `_generate_content` and `_repair_content` prompts:

```
IMPORT RULES:
- NEVER use relative imports (from . import X, from .module import X).
- The workspace root is on sys.path. Use absolute imports: from module import X.
- For files in subdirectories (e.g. src/models/resnet.py importing src/utils.py),
  import as: from utils import X  (NOT from ..utils import X).
```

---

## [2026-06-01] Bug: Plan Rejection Triggers Re-planning Instead of Pipeline Stop

**Context:** Clicking "거절" (Reject) in the ApprovalDialog continued to Phase 2 with a new plan round, identical to "수정 요청" (Modify).

**Root cause:** `phase1_planning.py` only checked `gate.is_approved` (True for "approve") and treated everything else — including "reject" — as a modify request requiring re-planning:

```python
# Before (broken): both reject and modify fall through to re-plan
if gate.is_approved:
    return bundle
# REJECT or MODIFY — inject feedback and re-plan  ← "reject" falls here
feedback = gate.feedback or "..."
```

`ApprovalGate` had a `gate.action` attribute with values `"approve"` / `"reject"` / `"modify"` — it was simply never checked.

**Fix:** Added an explicit `gate.action == "reject"` branch that raises `RuntimeError`, propagating to the orchestrator's `except` block and terminating the run as `"failed"`.

```python
if gate.action == "reject":
    raise RuntimeError(f"[Phase 1] Research plan rejected by user: {reason}")
# MODIFY only below this point
feedback = gate.feedback or "..."
```

---

## [2026-06-01] Bug: ProposalSheet "실행하기" → "세션을 찾을 수 없습니다"

**Context:** Clicking "실행하기" (Execute) on an extension proposal navigated to a blank "session not found" error screen.

**Root cause:** `acceptExtensionProposal()` created a new run via `POST /api/v1/research` and returned `run_id`. `onNewRun(run_id)` called `handleSelectSession(run_id)`, which updated `selectedRunId` and `viewMode = 'session'` — but never added the new session to the `sessions[]` state array. `SessionView` looked up `sessions.find(s => s.run_id === run_id)` and found nothing.

**Fix:** Added `handleNewSession(runId, topic, goal)` in `Home.tsx` that:
1. Constructs a minimal `Session` object
2. Prepends it to `sessions` state (same pattern as `handleStartResearch`)
3. Sets `selectedRunId` and navigates to session view

Also added `'queued'` to the `SessionStatus` union type (it was missing, only had `running | completed | failed | paused`).

---

## Ongoing / Open Issues

| Issue | Status | Notes |
|-------|--------|-------|
| Phase 3 실험 실제 성공 여부 (result.json 생성) | 🔄 Testing | Relative import fix applied — next run will verify |
| L3-1-6 거절 후 세션 상태 UI 반영 | 🔄 Re-test needed | Backend fixed; UI `failed` 상태 표시 재확인 |
| L3-3 전체 (터미널 스트리밍, context injection) | ⬜ Pending | Phase 3 실행 성공 필요 |
| L3-4 ProposalSheet 실행하기 재테스트 | ⬜ Pending | `handleNewSession` fix 이후 |

---

*Updated: 2026-06-01 | Next: L3 Phase 2 & 3 verification*
