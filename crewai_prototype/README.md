# MARS — CrewAI Prototype (V4)

**End-to-end ML research automation with a 5-phase pipeline, direct LLM call architecture, and 5-gate human-in-the-loop control.**

This is the reference implementation of the MARS pipeline, built on CrewAI and FastAPI. It is end-to-end verified and serves as the baseline for framework comparison against the AutoGen and LangGraph prototypes.

---

## Architecture

```
Phase 0  Workspace Setup + Preflight Q&A
Phase 1  Planning (Planner → Designer) + Human Approval Gate
Phase 2  Staged Code Generation (3 stages, dependency-injected) + Repair Loop
Phase 3  Experiment Execution + Analyzer + Repair Loop
Phase 4  Paper Writing (7 sections) + Quality Gate + Extension Proposals
```

Each phase writes structured JSON handoffs to `outputs/<run_id>/handoff/` — no raw text is passed between agents.

---

## Project Structure

```
crewai_prototype/
├── phases/                  # Phase 0–4 pipeline logic
│   ├── phase0_workspace.py
│   ├── phase1_planning.py
│   ├── phase2_coding.py
│   ├── phase3_execution.py
│   └── phase4_writing.py
│
├── orchestration/           # HitL gates and pipeline control
│   ├── approval_registry.py # Plan approval gate (approve / modify / reject)
│   ├── pipeline_orchestrator.py
│   ├── preflight_clarifier.py
│   └── ...
│
├── runtime/                 # Event store, SSE streaming, session store
│   ├── event_store.py
│   └── ...
│
├── core/                    # Shared models and utilities
│   ├── handoff_models.py    # PlanBundle, CodingResult, ExecutorResult, ...
│   ├── llm_factory.py
│   └── ...
│
├── crew_tools/              # CrewAI tools (RunCommandTool, WorkspaceWriteTool, ...)
├── pipeline_config/         # Constants and experiment profile rules
├── profiles/                # VisionClassification, TabularSupervised, ...
├── entrypoints/
│   ├── api.py               # FastAPI application entry point
│   └── cli.py
│
├── requirements.txt
├── config.yaml
└── .env.example
```

---

## Quick Start

### 1. Install dependencies

```bash
cd crewai_prototype
conda create -n mars python=3.11 -y && conda activate mars
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Open .env and add your API key (OPENAI_API_KEY or ANTHROPIC_API_KEY)
```

### 3. Start the backend

```bash
python -m uvicorn entrypoints.api:app --host 0.0.0.0 --port 8000 --reload
```

Health check:
```bash
curl http://localhost:8000/api/v1/sessions
```

---

## API Reference

### Start a research run

```bash
POST /api/v1/research
Content-Type: application/json

{
  "topic": "ResNet-18 vs ViT-tiny on CIFAR-10",
  "goal": "Compare top-1 accuracy for 10 epochs",
  "domain": "Computer Vision",
  "preferred_frameworks": "PyTorch",
  "max_experiments": 1,
  "time_limit_minutes": 30
}
```

Response: `{ "run_id": "...", "session_id": "...", "status": "running" }`

### Stream events (SSE)

```bash
GET /api/v1/research/{run_id}/stream
```

### Check status

```bash
GET /api/v1/research/{run_id}/status
```

### Human-in-the-loop gates

```bash
# Phase 1 plan approval
POST /api/v1/runs/{run_id}/approve        # { "action": "approve" | "modify" | "reject", "feedback": "..." }

# Phase 2/3 code repair guidance
POST /api/v1/runs/{run_id}/guidance       # { "hint": "...", "action": "retry" | "skip" }

# Phase 3 context injection
POST /api/v1/runs/{run_id}/inject         # { "context": "..." }
```

---

## Agent LLM Configuration

Each agent can use a different LLM. Edit the `agent_llm_mapping` section in `config.yaml`:

```yaml
agent_llm_mapping:
  planner:
    provider: "anthropic"
    model: "claude-sonnet-4-6"
    temperature: 0.3
  code_generator:
    provider: "anthropic"
    model: "claude-sonnet-4-6"
    temperature: 0.2
  paper_writer:
    provider: "openai"
    model: "gpt-4o"
    temperature: 0.5
```

| Provider    | Env variable          | Example models                                    |
|-------------|----------------------|---------------------------------------------------|
| `anthropic` | `ANTHROPIC_API_KEY`  | `claude-sonnet-4-6`, `claude-opus-4-7`            |
| `openai`    | `OPENAI_API_KEY`     | `gpt-4o`, `gpt-4o-mini`                          |
| `google`    | `GOOGLE_API_KEY`     | `gemini-2.5-pro`, `gemini-2.5-flash`              |

---

## Key Design Decisions

| ADR | Decision |
|-----|----------|
| [ADR-001](../docs/decisions/ADR-001-direct-llm-calls.md) | Direct LLM calls for code generation (no CrewAI tool calling) |
| [ADR-004](../docs/decisions/ADR-004-staged-code-generation.md) | Staged code generation with dependency injection |
| [ADR-008](../docs/decisions/ADR-008-repair-loop-escalation.md) | Three-tier repair loop: Auto → Human → Stub |
| [ADR-011](../docs/decisions/ADR-011-phase3-analyzer-stderr-context.md) | Separate stderr/stdout context in Phase 3 Analyzer |
| [ADR-014](../docs/decisions/ADR-014-windows-asyncio-proactor-event-loop-blocking.md) | Windows asyncio ProactorEventLoop constraint |

See [docs/decisions/](../docs/decisions/) for all 14 ADRs.

---

## Outputs

Each run writes artifacts to `outputs/<run_id>/`:

```
outputs/<run_id>/
├── workspace/
│   └── src/          # Generated experiment code (main.py, config.py, model.py, ...)
├── results/
│   └── result.json   # Experiment metrics
├── paper/
│   └── paper.md      # Auto-generated research paper
├── handoff/          # JSON handoffs between phases
└── logs/             # Execution logs
```

---

## Event Types

The SSE stream emits structured events. Key types:

| Event type | Description |
|------------|-------------|
| `SYSTEM_START` / `SYSTEM_END` | Pipeline start / completion |
| `PHASE_START` / `PHASE_COMPLETE` | Phase boundary markers |
| `PLAN_AWAITING_APPROVAL` | Phase 1 gate — requires user action |
| `USER_GUIDANCE_NEEDED` | Phase 2/3 repair gate — requires user hint |
| `exec_stdout` | Live stdout from experiment script |
| `FILE_GENERATED` | Code file written to workspace |
| `SMOKE_TEST_DONE` | Phase 2 import check result |
| `SECTION_DRAFT_DONE` | Paper section written (includes quality score) |
| `token_budget_snapshot` | Token usage progress |

---

## Troubleshooting

**`ModuleNotFoundError` on generated code** — Absolute import rule enforced; see [ADR-009](../docs/decisions/ADR-009-generated-code-import-rules.md).

**HTTP server freezes after Phase 2 repair** — Windows asyncio ProactorEventLoop issue; restart the server. See [ADR-014](../docs/decisions/ADR-014-windows-asyncio-proactor-event-loop-blocking.md).

**Approval gate times out** — Default timeout is 3600s. Set `RESEARCH_PIPELINE_APPROVAL_TIMEOUT_SECS=60` for testing.

**API key error** — Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env`. At least one provider must be configured.
