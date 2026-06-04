# ARCHITECTURE.md — Research Automation System V4

## 1. System Overview

```
                         ┌──────────────────────────────────────────────────────────┐
                         │                  HTTP CLIENT (UI / CLI)                  │
                         └────────────┬───────────────────────────┬─────────────────┘
                                      │  REST / SSE                │  POST /approve
                                      ▼                            ▼
                         ┌─────────────────────────────────────────────────────────┐
                         │                  FastAPI App  (api/)                    │
                         │  POST /runs        GET /runs/{id}/stream                │
                         │  POST /runs/{id}/approve                                │
                         │  POST /runs/{id}/guidance   GET /runs/{id}/status       │
                         └────────────────────────┬────────────────────────────────┘
                                                  │
                                                  ▼
                         ┌─────────────────────────────────────────────────────────┐
                         │              PipelineOrchestrator  (orchestration/)     │
                         │                                                          │
                         │  Thread per run:                                         │
                         │  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐ │
                         │  │ Phase 0  │  │ Phase 1  │  │      Phase 2          │ │
                         │  │Workspace │→ │ Planning │→ │  Staged Coding Loop   │ │
                         │  │  Setup   │  │ + Design │  │  (never gives up)     │ │
                         │  └──────────┘  └────┬─────┘  └──────────┬────────────┘ │
                         │                     │ APPROVAL GATE       │             │
                         │                     ▼                     ▼             │
                         │               asyncio.Event         ┌──────────┐        │
                         │               (blocks thread        │ Phase 3  │        │
                         │                until user           │Execution │        │
                         │                approves)            └────┬─────┘        │
                         │                                          ▼              │
                         │                                     ┌──────────┐        │
                         │                                     │ Phase 4  │        │
                         │                                     │  Writing │        │
                         │                                     └──────────┘        │
                         └─────────────────────────────────────────────────────────┘
                                    │                      │
                    ┌───────────────┘                      └─────────────────────┐
                    ▼                                                             ▼
     ┌──────────────────────────┐                            ┌────────────────────────────┐
     │   runtime/               │                            │   core/                    │
     │   EventStore (JSONL)     │                            │   HandoffStore (JSON)       │
     │   SessionStore (JSON)    │                            │   LLMFactory               │
     │   StreamService (SSE)    │                            │   LLMCostTracker           │
     └──────────────────────────┘                            └────────────────────────────┘
                    │
                    ▼
     ┌──────────────────────────┐
     │   outputs/{run_id}/      │
     │   ├─ workspace/          │
     │   │  ├─ src/             │
     │   │  ├─ results/         │
     │   │  └─ logs/            │
     │   ├─ handoff/            │
     │   ├─ paper/              │
     │   └─ events.jsonl        │
     └──────────────────────────┘
```

---

## 2. Core Design Decisions

### 2.1 User Approval Gate: asyncio.Event + Long-Poll REST

The approval gate must block the pipeline thread without blocking the web server. The mechanism:

1. When Phase 1 (Planner + Designer) completes, `PipelineOrchestrator` stores a `PlanApprovalGate` object keyed by `run_id` in a dict protected by `threading.Lock`.
2. The gate contains:
   - `plan_payload: dict` — the full plan to show the user
   - `approved: threading.Event` — blocks the pipeline thread on `.wait()`
   - `feedback: str | None` — optional user revision instructions injected before unblocking
3. The API layer exposes `POST /runs/{id}/approve` which sets `approved` and optionally writes feedback.
4. `GET /runs/{id}/stream` continues working during the wait — it emits a `PLAN_AWAITING_APPROVAL` event so the UI can render the approval widget.
5. Timeout: if no approval arrives within `approval_timeout_seconds` (default 3600), the gate auto-approves with a warning event.

This design is:
- **Non-blocking for the web server**: FastAPI/uvicorn threads are never blocked; the pipeline runs in a `daemon=True` background thread.
- **Resumable**: The SSE stream keeps flowing. The UI always knows the current state.
- **Auditable**: Approval/rejection events are written to EventStore.

### 2.2 "Ask the User When Stuck" Mechanism

The Coder loop can get stuck when LLM repair attempts all fail. Instead of a hard circuit-breaker stop, the system enters a `WAITING_FOR_GUIDANCE` state:

1. After `max_llm_repair_attempts` (default 5) consecutive failures on the same file, a `GuidanceRequest` object is stored (similar to `PlanApprovalGate`).
2. A `USER_GUIDANCE_NEEDED` event is emitted with the error context, the file that failed, and a summary of repair attempts.
3. The pipeline thread blocks on `guidance_event.wait()`.
4. The UI renders an input form. The user types guidance (e.g. "switch to sklearn instead of torch" or "use a simpler loss function").
5. `POST /runs/{id}/guidance` delivers the text, sets the event, and the pipeline retries with the guidance injected into the next LLM prompt.
6. There is no attempt cap at the guidance level — after each guidance round, `max_llm_repair_attempts` resets.

### 2.3 Staged Coding Maps to CrewAI Tasks

Each "stage" is a separate CrewAI `Task` assigned to the same `FileCoder` agent. The orchestrator builds and kicks off one `Crew` per stage (not one mega-Crew), which gives fine-grained control over interleaved syntax/import checks between stages.

```
Stage 1 (scaffold + config):
  Tasks: [write pyproject.toml, write requirements.txt, write config.yaml/json]
  Check: python -m py_compile {file} for each .py file in stage

Stage 2 (utility/data modules — bottom of dep graph):
  Tasks: [write utils.py, write data_loader.py, write metrics.py, ...]
  Check: python -c "import {module}" for each module

Stage 3 (main entry point):
  Tasks: [write main.py / experiment_impl.py]
  Check: python -c "import {entry_module}" then python {entry_module} --dry-run
```

After each stage's check, results are presented to the user via SSE before the pipeline proceeds to the next stage.

### 2.4 Repair Loop Without Circuit Breaker

The repair loop in `StagedCoderService` uses a per-file attempt counter with no hard cap. The progression:

```
attempt 1..N (LLM auto-repair):
  → emit REPAIR_ATTEMPT event
  → LLM reads error + current file + context
  → writes new version
  → re-runs syntax/import check
  → if pass: emit FILE_FIXED, move on
  → if fail and attempt < max_llm_repair_attempts: continue loop
  → if fail and attempt >= max_llm_repair_attempts:
      emit USER_GUIDANCE_NEEDED
      block on guidance_event.wait()
      inject guidance text into next repair prompt
      reset attempt counter to 0
      continue repair loop  ← NEVER exits here

The loop only exits when:
  1. Syntax/import check passes (success)
  2. User explicitly cancels the run via DELETE /runs/{id}
```

### 2.5 Workspace Directory Setup

At `POST /runs`, the client may supply `output_path`. If omitted, the server defaults to `{OUTPUTS_ROOT}/{run_id}/`. The orchestrator:

1. Creates `output_path/workspace/` (the code sandbox)
2. Creates `output_path/handoff/` (JSON handoff files)
3. Creates `output_path/paper/` (Writer output)
4. Creates `output_path/logs/` (execution logs)
5. Symlinks or copies scaffold files from `scaffolds/{profile}/` into `workspace/`

All subsequent agent tool calls (`WorkspaceReadTool`, `WorkspaceWriteTool`) are sandboxed to `output_path/workspace/` — path traversal outside the root raises an error before the LLM receives any response.

---

## 3. Module Breakdown

### 3.1 `api/` — HTTP Layer

| Module | Responsibility |
|--------|---------------|
| `api/app.py` | FastAPI factory, CORS, route registration |
| `api/routes/runs.py` | POST /runs, GET /runs/{id}/status, DELETE /runs/{id} |
| `api/routes/approval.py` | POST /runs/{id}/approve, POST /runs/{id}/guidance |
| `api/routes/stream.py` | GET /runs/{id}/stream (SSE), GET /runs/{id}/events |
| `api/routes/artifacts.py` | GET /runs/{id}/artifacts, GET /runs/{id}/artifacts/{path} |
| `api/schemas.py` | Pydantic request/response models |

### 3.2 `orchestration/` — Pipeline Control

| Module | Responsibility |
|--------|---------------|
| `orchestration/pipeline_orchestrator.py` | Top-level run lifecycle: prepare → phase 0-4 → finalize |
| `orchestration/approval_gate.py` | `PlanApprovalGate` dataclass + `ApprovalRegistry` (thread-safe dict) |
| `orchestration/guidance_registry.py` | `GuidanceRequest` dataclass + `GuidanceRegistry` |
| `orchestration/input_normalizer.py` | Normalize API request dict (existing, reused) |

### 3.3 `phases/` — Phase Implementations

| Module | Responsibility |
|--------|---------------|
| `phases/phase0_workspace.py` | WorkspaceSetupService: scaffold materialization, dir creation |
| `phases/phase1_planning.py` | PlannerDesignerService: runs Planner+Designer Crew, returns `PlanBundle` |
| `phases/phase2_coding.py` | StagedCoderService: 3-stage loop with repair + user guidance |
| `phases/phase3_execution.py` | ExecutionService: runs experiment, collects results |
| `phases/phase4_writing.py` | WriterService: section-by-section paper generation with self-verify |

### 3.4 `crew_agents/` — CrewAI Agent Factories (mostly reused)

| Module | Responsibility |
|--------|---------------|
| `crew_agents/planner.py` | `make_planner_agent(llm)` |
| `crew_agents/designer.py` | `make_designer_agent(llm)` |
| `crew_agents/file_coder.py` | `make_file_coder_agent(llm)` |
| `crew_agents/executor.py` | `make_executor_agent(llm)` |
| `crew_agents/writer.py` | `make_writer_agent(llm)` — extended for section-by-section |

### 3.5 `core/` — Shared Infrastructure (reused as-is)

| Module | Responsibility |
|--------|---------------|
| `core/handoff_models.py` | Pydantic handoff shapes between pipeline phases |
| `core/handoff_store.py` | JSON persistence for handoff data |
| `core/llm_factory.py` | Multi-provider LLM instantiation |
| `core/llm_retry.py` | Retry policy + `LLMCostTracker` singleton |
| `core/logger.py` | `ResearchLogger` — JSONL structured logging |

### 3.6 `crew_tools/` — CrewAI Tool Implementations (reused as-is)

| Module | Responsibility |
|--------|---------------|
| `crew_tools/workspace_tools.py` | `WorkspaceReadTool`, `WorkspaceWriteTool`, `WorkspaceListTool` |
| `crew_tools/execution_tools.py` | `RunCommandTool`, `ReadResultTool` |
| `crew_tools/edit_tool.py` | `FileEditTool` (patch-level edits) |
| `crew_tools/report_tools.py` | `WriteReportTool` |

### 3.7 `runtime/` — Event & Session Persistence (reused as-is)

| Module | Responsibility |
|--------|---------------|
| `runtime/event_store.py` | `EventStore` — append-only JSONL per run |
| `runtime/session_store.py` | `SessionStore` — session metadata JSON per run |
| `runtime/models.py` | `RunEvent`, `RunSession`, `ArtifactRecord` dataclasses |
| `runtime/stream_service.py` | `StreamService` — async SSE tail of EventStore |
| `runtime/state_calculator.py` | Builds UI-ready session/event dicts |

---

## 4. Data Flow Between Phases

```
Phase 0 (Workspace Setup)
  Input:  ResearchRequest (topic, output_path, profile)
  Output: WorkspaceSetupResult
            workspace_root: Path
            scaffold_files: list[str]   ← already-written stable files
  Writes: handoff/workspace_setup.json

Phase 1 (Planning + Design)
  Input:  WorkspaceSetupResult + ResearchRequest
  Output: PlanBundle
            planner_result: PlannerResult   ← existing model, reused
            designer_result: DesignerResult ← existing model, reused
            file_tree: list[FileNodeSpec]   ← NEW: AST-level per-file spec
            dep_graph: dict[str, list[str]] ← NEW: adjacency list
            staged_files: StagedFileList    ← NEW: stage 1/2/3 assignments
  Writes: handoff/plan_bundle.json
  GATE:   approval_gate.wait()   ← blocks until POST /approve

Phase 2 (Staged Coding)
  Input:  PlanBundle
  Output: CodingResult
            stage_results: list[StageResult]
            all_files_passed: bool
            files_written: list[str]
  Writes: workspace/* (source files)
          handoff/coding_result.json

Phase 3 (Execution)
  Input:  CodingResult
  Output: ExecutionResult
            return_code: int
            duration_s: float
            result_json_path: str
            metrics: dict[str, float]
            log_path: str
  Writes: workspace/results/result.json
          handoff/execution_result.json

Phase 4 (Writing)
  Input:  PlanBundle + ExecutionResult
  Output: WritingResult
            paper_path: str
            sections_completed: list[str]
            word_count: int
  Writes: paper/paper.md
          handoff/writing_result.json
```

---

## 5. Technology Choices with Rationale

| Choice | Rationale |
|--------|-----------|
| **CrewAI** | Existing investment; Agent + Task + Crew abstractions map cleanly to the staged coding model. One Crew per stage gives per-stage observability. |
| **FastAPI + uvicorn** | Already in use. SSE via `StreamingResponse` works well with the async event loop. |
| **`threading.Event` for gates** | Pipeline runs in daemon threads. `threading.Event.wait(timeout)` is the simplest correct primitive for a blocking gate in a thread context. No asyncio crossing needed. |
| **`asyncio.Queue` avoided for gates** | The pipeline runs in a `threading.Thread`, not an asyncio coroutine. Mixing asyncio primitives across thread boundaries requires `loop.call_soon_threadsafe`, which adds complexity. `threading.Event` is simpler and sufficient. |
| **SSE for streaming** | Already implemented in `StreamService`. The approval and guidance events are simply new `event_type` values emitted into the same stream. |
| **Per-stage Crew (not one mega-Crew)** | One Crew per stage means: (a) errors in stage 2 don't corrupt stage 1 context; (b) the orchestrator inspects check results between stages and decides whether to proceed or enter repair; (c) easier to inject user guidance between stages. |
| **JSONL EventStore** | Append-only, crash-safe, tail-readable. SSE streaming is a tail reader — no DB required. |
| **Pydantic v2 for all models** | Strict validation at every boundary. `model_validate_json` / `model_dump_json` for zero-copy serialization. |

---

## 6. New Event Types Added to `runtime/models.py`

These are additions to the existing `EVENT_TYPES` tuple:

```
PLAN_AWAITING_APPROVAL    — gate is open, UI must render approval widget
PLAN_APPROVED             — user approved (or timeout)
PLAN_REVISED              — user submitted feedback, replanning in progress
STAGE_START               — stage N of coding beginning
STAGE_CHECK_PASS          — syntax/import check passed after stage N
STAGE_CHECK_FAIL          — check failed, entering repair
REPAIR_ATTEMPT            — LLM repair attempt #N for file X
FILE_FIXED                — repair succeeded
USER_GUIDANCE_NEEDED      — LLM exhausted attempts, waiting for user input
USER_GUIDANCE_RECEIVED    — user submitted guidance, repair resuming
EXECUTION_START           — experiment subprocess launched
EXECUTION_DONE            — experiment subprocess exited
SECTION_DRAFT_START       — writer starting section X
SECTION_DRAFT_DONE        — writer completed section X (self-verified)
PAPER_DONE                — final paper written
```
