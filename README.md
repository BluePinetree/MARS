<div align="center">

# MARS
### Multi-Agent Research System

**End-to-end ML research automation — from a natural language question to a structured paper —
with human-in-the-loop control at every critical gate.**

**The first open-source system to implement and compare the same ML research pipeline
across CrewAI, AutoGen, and LangGraph.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)](docs/DEVLOG.md)

[Overview](#overview) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Why MARS](#why-mars) · [Human-in-the-Loop](#human-in-the-loop) · [Roadmap](#roadmap) · [Citation](#citation)

</div>

---

> **Demo GIF coming soon** — screen recording in progress. See [examples/](examples/) for sample pipeline outputs.

---

## Overview

MARS automates the full ML research lifecycle from a single natural-language topic:

```
"Compare ResNet-18 vs ViT-tiny on CIFAR-10"
        ↓
 [Phase 0] Dataset & compute constraints clarified via Q&A
 [Phase 1] Research plan generated → human approves
 [Phase 2] Python experiment code generated in staged order (19 files, dependency-injected)
 [Phase 3] Experiment executed → auto-repaired if it fails
 [Phase 4] Paper written section-by-section with quality gate
        ↓
 paper/paper.md  +  results/result.json  +  extension proposals
```

**What makes MARS different:**

- **Framework comparison** — the same pipeline implemented in CrewAI, AutoGen, and LangGraph, enabling empirical benchmarking of agent frameworks on a real task
- **Full-stack** — Python backend with SSE streaming + React UI (one of only two open systems with both; the other is GPT-Researcher, which is web-research-only)
- **Structured Human-in-the-Loop** — 5 distinct interaction points, each with a dedicated UI component and API endpoint
- **Engineering rigor** — 14 Architecture Decision Records (ADRs) documenting every non-obvious design choice

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Research Topic (natural language)            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  Phase 0 · Workspace Setup    │  Preflight Q&A → user confirms
          │  + Preflight Clarification    │  dataset, compute, eval metric
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  Phase 1 · Planning           │  Planner → Designer
          │  + Human Approval Gate  ◀─────┤  approve / request revision / reject
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  Phase 2 · Staged Coding      │  Stage 1 (config) → 2 (model/data)
          │  + Repair Loop + Smoke Test   │  → 3 (entry point)
          └──────────┬─────────┬──────────┘  token budget · guidance drawer
                     │         │
                     │  ┌──────▼──────────────────┐
                     │  │ USER_GUIDANCE_NEEDED     │  if > N repair failures
                     │  └─────────────────────────┘
                     │
          ┌───────────▼───────────────────┐
          │  Phase 3 · Experiment Run     │  python src/main.py → stdout stream
          │  + Analyzer + Repair Loop     │  terminal pane · context injection
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  Phase 4 · Paper Writing      │  7 sections + coherence revision
          │  + Extension Proposals        │  quality gate (score ≥ 0.70)
          └───────────────┬───────────────┘
                          │
          ┌───────────────▼───────────────┐
          │  paper/paper.md               │  Markdown paper
          │  results/result.json          │  Experiment metrics
          └───────────────────────────────┘

  React UI ──── SSE stream ──── FastAPI ──── Agent pipeline
```

---

## Quick Start

### Prerequisites

| Dependency | Version |
|-----------|---------|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| pnpm | ≥ 8 |
| API key | OpenAI **or** Anthropic |

### 1. Clone & install

```bash
git clone https://github.com/BluePinetree/mars.git
cd mars
```

**Backend:**
```bash
cd crewai_prototype
conda create -n mars python=3.11 -y && conda activate mars
pip install -r requirements.txt
cp .env.example .env          # add your API key
```

**Frontend:**
```bash
cd research_system_ui
pnpm install
```

### 2. Run

```bash
# Terminal 1 — backend
cd crewai_prototype
python -m uvicorn entrypoints.api:app --port 8000

# Terminal 2 — frontend
cd research_system_ui
pnpm dev
```

Open [http://localhost:5173](http://localhost:5173), click **New Research**, and enter a topic.

### 3. Or via API directly

```bash
curl -X POST http://localhost:8000/api/v1/research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "ResNet-18 vs ViT-tiny on CIFAR-10",
    "goal": "Compare top-1 accuracy for 5 epochs",
    "domain": "Computer Vision",
    "preferred_frameworks": "PyTorch",
    "max_experiments": 1,
    "time_limit_minutes": 30
  }'
```

See [examples/](examples/) for sample outputs.

---

## Human-in-the-Loop

MARS treats human oversight as a first-class design principle, not an afterthought.
There are **5 distinct interaction gates**, each with its own UI component and API endpoint:

| Gate | Phase | User Action | UI Component |
|------|-------|-------------|--------------|
| **Preflight Q&A** | 0 | Answer ≤4 questions (dataset, compute, metrics, context) | `PreflightFlow` |
| **Plan Approval** | 1 | Approve / request revision / reject the research plan | `ApprovalDialog` |
| **Code Repair Guidance** | 2 | Provide a fix hint when auto-repair exhausts retries | `GuidanceDrawer` |
| **Context Injection** | 3 | Send domain knowledge mid-execution | `ContextInjectionInput` |
| **Extension Proposals** | 4 | Choose follow-up experiments from AI suggestions | `ProposalSheet` |

"Approve / request revision / reject" at the plan gate gives the user meaningful control:
- **Approve** → proceed to code generation
- **Request revision** → re-plan with feedback (up to 5 rounds)
- **Reject** → hard stop, pipeline terminates cleanly

---

## Why MARS?

### vs. similar systems

| System | Stars | End-to-End Pipeline | Streaming UI | Multi-Framework | HITL Gates | arXiv |
|--------|-------|---------------------|--------------|-----------------|------------|-------|
| **MetaGPT** | 68k | Software only | ✗ | ✗ | ✗ | ✓ |
| **AI-Scientist** | 14k | ML research ✓ | ✗ | ✗ | ✗ | ✓ |
| **GPT-Researcher** | 27k | Web research only | ✓ | ✗ | ✗ | ✗ |
| **AgentLaboratory** | 5k | ML research ✓ | ✗ | ✗ | ✓ limited | ✓ |
| **AIDE** | 1.3k | ML coding only | ✗ | ✗ | ✗ | ✓ |
| **MARS** (ours) | — | ML research ✓ | ✓ | ✓ (3 frameworks) | ✓ 5 gates | planned |

### Key engineering contributions

1. **Direct LLM call architecture** — eliminates tool-call compliance failures that plague CrewAI-based code writers ([ADR-001](docs/decisions/ADR-001-direct-llm-calls.md))
2. **Staged code generation with dependency injection** — files generated in dependency order; each file receives actual exported symbols of its dependencies as context ([ADR-004](docs/decisions/ADR-004-staged-code-generation.md))
3. **Three-tier repair loop** — auto-repair → human guidance → stub fallback, with typed escalation events ([ADR-008](docs/decisions/ADR-008-repair-loop-escalation.md))
4. **14 Architecture Decision Records** — every non-obvious design choice documented with context, alternatives considered, and consequences

---

## Benchmark

> **Work in progress.** The CrewAI implementation (V4) is stable and end-to-end verified.
> AutoGen and LangGraph implementations are in progress.
> Results will be published here and in an accompanying arXiv paper.

**Planned benchmark tasks:**

| Task | Domain | Dataset | Primary Metric |
|------|--------|---------|----------------|
| T1 | Vision Classification | CIFAR-10 | Top-1 Accuracy |
| T2 | Vision Classification | CIFAR-100 | Top-1 / Top-5 |
| T3 | Tabular Classification | Titanic | ROC-AUC |
| T4 | Tabular Regression | California Housing | RMSE / R² |
| T5 | Time Series Forecasting | AirPassengers | SMAPE |

**Comparison dimensions:** Task success rate · End-to-end latency · Token usage · Code repair attempts · Paper quality score

---

## Project Structure

```
mars/
├── crewai_prototype/          # CrewAI implementation (V4 — end-to-end stable)
│   ├── phases/                # Phase 0–4 pipeline logic
│   ├── orchestration/         # Approval / guidance / cancellation gates
│   ├── runtime/               # Event store, session store, SSE streaming
│   ├── core/                  # Handoff models, LLM factory
│   ├── pipeline_config/       # Constants and experiment profile rules
│   └── entrypoints/           # FastAPI application
│
├── autogen_prototype/         # AutoGen implementation (in progress)
├── langgraph_prototype/       # LangGraph implementation (in progress)
│
├── research_system_ui/        # Shared React frontend (Vite + TypeScript)
│   └── client/src/
│       ├── components/        # ApprovalDialog, GuidanceDrawer, TerminalPane, …
│       ├── pages/             # Dashboard, SessionView, ComparisonView
│       └── lib/               # API client, SSE hook, types
│
├── examples/                  # Sample pipeline outputs (paper + result.json)
│
└── docs/
    ├── ARCHITECTURE.md        # System design and component overview
    ├── DEVLOG.md              # Chronological engineering diary
    ├── API_SPEC.md            # REST API reference
    └── decisions/             # 14 Architecture Decision Records (ADR-001–014)
```

---

## Roadmap

- [x] CrewAI V4 pipeline — Phase 0–4, end-to-end verified
- [x] Real-time SSE streaming UI
- [x] Human-in-the-loop: 5 distinct gates (preflight, approval, guidance ×2, extension)
- [x] Token budget tracking, failure pattern detection
- [x] Three-tier repair loop (auto → human → stub)
- [x] 14 Architecture Decision Records
- [ ] AutoGen implementation — stable end-to-end
- [ ] LangGraph implementation — stable end-to-end
- [ ] Benchmark suite — 5 tasks × 3 frameworks
- [ ] ComparisonView — side-by-side framework metrics in UI
- [ ] Docker Compose — one-command local setup
- [ ] arXiv preprint

---

## Documentation

<details>
<summary>Architecture Decision Records (14 ADRs)</summary>

| ADR | Decision |
|-----|----------|
| [ADR-001](docs/decisions/ADR-001-direct-llm-calls.md) | Direct LLM calls instead of CrewAI tool calling for code generation |
| [ADR-002](docs/decisions/ADR-002-json-handoff.md) | JSON-structured handoffs between agents |
| [ADR-003](docs/decisions/ADR-003-sse-streaming.md) | SSE over WebSocket for event streaming |
| [ADR-004](docs/decisions/ADR-004-staged-code-generation.md) | Staged code generation with dependency injection |
| [ADR-005](docs/decisions/ADR-005-hitl-gate-architecture.md) | HitL gate architecture (threading.Event + GuidanceGate) |
| [ADR-006](docs/decisions/ADR-006-event-taxonomy.md) | Fine-grained event types over generic AGENT_MESSAGE |
| [ADR-007](docs/decisions/ADR-007-event-normalization.md) | Exact-match-first event type normalization |
| [ADR-008](docs/decisions/ADR-008-repair-loop-escalation.md) | Three-tier repair loop: Auto → Human → Stub |
| [ADR-009](docs/decisions/ADR-009-generated-code-import-rules.md) | Absolute imports only in generated code |
| [ADR-010](docs/decisions/ADR-010-importlib-sys-modules-registration.md) | Register module in sys.modules before exec_module |
| [ADR-011](docs/decisions/ADR-011-phase3-analyzer-stderr-context.md) | Separate stderr/stdout context in Phase 3 Analyzer |
| [ADR-012](docs/decisions/ADR-012-phase1-reject-vs-modify-branching.md) | Explicit reject branch in Phase 1 approval gate |
| [ADR-013](docs/decisions/ADR-013-phase3-success-criterion-rc-vs-result-json.md) | return_code=0 as authoritative success gate |
| [ADR-014](docs/decisions/ADR-014-windows-asyncio-proactor-event-loop-blocking.md) | Windows asyncio ProactorEventLoop blocking constraint |

</details>

| Document | Description |
|----------|-------------|
| [DEVLOG](docs/DEVLOG.md) | Chronological engineering diary — bugs, decisions, lessons |
| [Architecture](docs/ARCHITECTURE.md) | System design and component overview |
| [API Spec](docs/API_SPEC.md) | REST API reference |
| [Test Checklist](docs/test_checklist_v1.md) | L0–L5 integration test checklist |
| [Changelog](CHANGELOG.md) | Version history |

---

## Citation

```bibtex
@software{mars2026,
  author    = {Yun, Yunsu},
  title     = {MARS: Multi-Agent Research System — A Multi-Framework Benchmark
               for Autonomous ML Research Pipelines},
  year      = {2026},
  url       = {https://github.com/BluePinetree/mars},
  note      = {Active development}
}
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built with CrewAI · FastAPI · React · PyTorch · Anthropic Claude</sub>
</div>
