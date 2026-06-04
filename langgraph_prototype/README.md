# MARS — LangGraph Prototype

**Workflow-centric architecture using LangGraph's StateGraph.**

> **Status: In Progress** — Architecture is defined; end-to-end pipeline verification is ongoing. See [Roadmap](../README.md#roadmap).

This prototype implements the same MARS research pipeline using LangGraph. Six specialized agents collaborate step-by-step on a shared `ResearchState`, executing the full cycle: planning → experiment design → code generation → execution → analysis → paper writing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    StateGraph (LangGraph)                     │
│                                                               │
│  START → [Planner] → [Designer] → [Coder] → [Executor]      │
│                                        ↑          │          │
│                                        │    ┌─────┘          │
│                                        │    ↓                │
│                                   [Coder] ← [Analyzer]      │
│                                   (debug)      │             │
│                                               ↓             │
│                                          [Writer] → END     │
└─────────────────────────────────────────────────────────────┘
```

| Agent | Role | Default LLM |
|-------|------|-------------|
| Research Planner | Research planning + literature search | gpt-4o |
| Experiment Designer | Hypothesis, methodology, experiment design | gpt-4o |
| Code Generator | Experiment code generation + debug fixes | claude-sonnet-4-6 |
| Experiment Executor | Isolated execution + experiment tracking | gpt-4o-mini |
| Result Analyzer | Result analysis + goal attainment judgment | claude-sonnet-4-6 |
| Paper Writer | Academic report writing | gpt-4o |

### Key characteristics

- **General-purpose research system** — applicable to computer vision, NLP, time series forecasting, and more
- **Per-agent LLM selection** — each agent can use a different model
- **Automatic debug loop** — on experiment failure or unmet performance targets, code is automatically revised and re-run (up to 3 times)
- **Graceful degradation** — Pinecone, Docker, W&B fall back to local modes if not configured
- **Standard JSONL logging** — 12 event types, compatible with the shared MARS UI
- **CLI + REST API** — both terminal and FastAPI server modes supported

---

## Project Structure

```
langgraph_prototype/
├── main.py                     # CLI + FastAPI entry point
├── config.yaml                 # Per-agent LLM mapping
├── .env.example
├── requirements.txt
│
├── graph/
│   ├── state.py                # ResearchState TypedDict
│   ├── research_graph.py       # Node / edge / conditional branch definitions
│   └── builder.py              # Dependency injection + graph assembly
│
├── nodes/                      # Node functions (agent logic)
│   ├── base.py                 # Common helpers (LLM call, context builder)
│   ├── planner.py
│   ├── designer.py
│   ├── coder.py
│   ├── executor.py
│   ├── analyzer.py
│   └── writer.py
│
├── tools/
│   ├── pinecone_tool.py        # Pinecone vector search (RAG)
│   ├── docker_tool.py          # Docker code execution sandbox
│   └── wandb_tool.py           # W&B experiment tracking
│
├── tasks/                      # Celery async tasks
│   ├── celery_app.py
│   └── research_tasks.py
│
├── api/
│   └── server.py               # FastAPI server
│
├── utils/
│   └── logger.py               # Standard JSONL logger
│
└── tests/
    └── test_debug_loop.py
```

---

## Setup

### Prerequisites

- Python 3.10+
- (Optional) Docker Desktop — required for isolated code execution
- (Optional) Redis — required for Celery async tasks

```bash
cd langgraph_prototype

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate      # Linux/macOS
# venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` with your LLM API keys:

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
GOOGLE_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxx

# Optional external services
PINECONE_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
WANDB_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> Pinecone, Docker, and W&B API keys are optional — the system runs in fallback mode without them.

### Per-agent LLM configuration (optional)

```yaml
llm_config:
  planner:
    provider: "openai"
    model: "gpt-4o"
    temperature: 0.3
  coder:
    provider: "anthropic"
    model: "claude-sonnet-4-6"
    temperature: 0.2
```

| Provider    | Env variable         | Recommended for             |
|-------------|---------------------|-----------------------------|
| `openai`    | `OPENAI_API_KEY`    | Planner, Designer, Writer   |
| `openai`    | `OPENAI_API_KEY`    | Executor (lightweight)      |
| `anthropic` | `ANTHROPIC_API_KEY` | Coder, Analyzer             |
| `google`    | `GOOGLE_API_KEY`    | Fast response tasks          |

---

## Running

### CLI — synchronous

```bash
python main.py run \
  --topic "ResNet vs ViT on CIFAR-100" \
  --domain "Computer Vision" \
  --target-accuracy 0.85

# Full options
python main.py run \
  --topic "LSTM vs Transformer time series forecasting" \
  --domain "Time Series Forecasting" \
  --goal "Compare MAE and RMSE across models" \
  --data-path "./data/stock_prices.csv" \
  --output ./outputs \
  --target-accuracy 0.90 \
  --max-experiments 5 \
  --frameworks "PyTorch,scikit-learn"
```

### Interactive mode

```bash
python main.py interactive
```

### Dry run (validate graph structure without LLM calls)

```bash
python main.py dry-run
```

### FastAPI server

```bash
python main.py serve --port 8000
# API docs: http://localhost:8000/docs
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | System status |
| `/api/v1/config` | GET | Current agent LLM config |
| `/api/v1/config/agents` | PUT | Update agent LLM config dynamically |
| `/api/v1/research/run` | POST | Synchronous research run |
| `/api/v1/research/run/async` | POST | Celery async run |
| `/api/v1/research/status/{id}` | GET | Task status |
| `/api/v1/research/cancel/{id}` | POST | Cancel task |

### Celery async execution (optional)

```bash
# 1. Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# 2. Start Celery worker (separate terminal)
celery -A tasks.celery_app worker --loglevel=info --concurrency=2

# 3. Submit async run via API
curl -X POST http://localhost:8000/api/v1/research/run/async \
  -H "Content-Type: application/json" \
  -d '{"research_topic": "...", "research_domain": "..."}'
```

---

## Debug Loop (Core differentiator)

```
Executor → failure    → Coder (fix)      → Executor (retry)
Analyzer → below goal → Coder (improve)  → Executor → Analyzer
```

- **Execution failure loop** — Coder analyzes the error message and auto-fixes the code
- **Performance improvement loop** — Analyzer feedback is fed back into code revisions
- **Safety cap** — after 3 loops, the pipeline proceeds with the best available result

---

## Outputs

```
outputs/{run_id}/
├── generated_code/
│   ├── experiment.py
│   └── requirements.txt
├── results/
│   └── metrics.json
└── report.md
```

---

## Testing

```bash
# Test the debug loop scenario
PYTHONPATH=. python -m pytest tests/test_debug_loop.py -v

# Validate graph structure (no LLM calls)
python main.py dry-run
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `OPENAI_API_KEY not set` | Set the API key in `.env` |
| Docker connection failed | Ensure Docker Desktop is running; if not installed, the system runs in simulation mode |
| Celery connection failed | Start Redis: `docker run -d -p 6379:6379 redis:7-alpine` |
| Pinecone connection failed | Expected without API key — falls back to local mode automatically |
| W&B connection failed | Expected without API key — falls back to local JSON storage automatically |
| `ModuleNotFoundError` | Re-run `pip install -r requirements.txt` |
