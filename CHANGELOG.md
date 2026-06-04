# Changelog

All notable changes to MARS are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- ADR-011: Phase 3 Analyzer stderr context isolation
- ADR-012: Phase 1 approval gate explicit reject branch
- ADR-013: Phase 3 success criterion — rc=0 vs result.json.success
- ADR-014: Windows asyncio ProactorEventLoop blocking in pipeline threads
- Warning emit when experiment exits cleanly but result.json reports `success=false`

---

## [0.4.0] — 2026-06-03

### Added
- **Phase 3 Analyzer fix**: separate `stderr_tail` / `stdout_tail` / `return_code`
  template variables — Analyzer can now see the actual exception instead of
  stdout-truncated noise
- **Phase 1 reject gate**: explicit `gate.action == "reject"` branch raises
  `RuntimeError` and terminates the pipeline cleanly; previously reject was
  silently treated as modify
- `USER_GUIDANCE_NEEDED` escalation in Phase 3 after `MAX_EXEC_REPAIR_ATTEMPTS`
- ADR-006 through ADR-010 (event taxonomy, normalization, repair loop, import rules,
  importlib sys.modules registration)

### Fixed
- Phase 1 re-plan loop triggered on reject action (now hard stop)
- Phase 3 Analyzer blind to actual Python exceptions due to context truncation

---

## [0.3.0] — 2026-06-01

### Added
- **Staged code generation** (Phase 2): Stage 1 (config/utils) → Stage 2
  (model/data) → Stage 3 (entry point), with dependency injection at each stage
- **Token budget tracking**: `token_budget_snapshot` events + `TokenBudgetBar` UI
- **Smoke test** after Phase 2: importlib-based import check for all generated files
- **FILE_GENERATED**, **FILE_IMPORT_ERROR**, **FILE_FIXED** event types
- `GuidanceDrawer` UI component for Phase 2/3 repair escalation
- Phase 2 repair loop: auto-repair up to N attempts, then escalate to user
- Direct LLM call architecture for code generation (eliminates CrewAI tool-call
  compliance failures)
- ADR-001 through ADR-005

### Fixed
- `@dataclass` files failing import check (importlib sys.modules registration)
- Generated files using relative imports (enforced absolute-import rule)
- FileCoder never calling WorkspaceWriteTool (root cause: switched to direct LLM calls)

---

## [0.2.0] — 2026-05-21

### Added
- **Phase 1 HitL approval gate**: `PLAN_AWAITING_APPROVAL` → user approve /
  modify / reject → re-plan loop (up to `MAX_REPLAN_ROUNDS`)
- **Preflight clarification** (Phase 0): 4 structured Q&A gates before planning
- `ApprovalDialog` UI component
- `PreflightFlow` UI component with 60-second countdown per question
- `GuidanceRegistry` and `ApprovalRegistry` for gate state management
- SSE streaming: `EventSource` reconnection, `mergeLogEvents` deduplication
- `RunStatusRibbon`, `ContextInjectionInput`, `ProposalSheet` UI components

### Changed
- Agent handoffs migrated from free-text to typed JSON (`PlanBundle`, `CodingResult`,
  `ExecutorResult`, `AnalysisResult`)

---

## [0.1.0] — 2026-05-15

### Added
- Initial 5-phase pipeline: Workspace → Planning → Coding → Execution → Writing
- CrewAI-based agent implementation (Planner, Designer, Coder, Executor, Analyzer, Writer)
- FastAPI backend with SSE event streaming
- React frontend: Dashboard, LogView, Phase stepper, DetailPanel
- `runs/<run_id>/events.jsonl` event persistence
- `outputs/<run_id>/` workspace isolation per run
- Basic repair loop for Phase 2 (single agent, no escalation)
- Paper writing: 7 sections with quality gate (score ≥ 0.70)
- Extension proposals after Phase 4

---

[Unreleased]: https://github.com/BluePinetree/mars/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/BluePinetree/mars/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/BluePinetree/mars/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/BluePinetree/mars/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/BluePinetree/mars/releases/tag/v0.1.0
