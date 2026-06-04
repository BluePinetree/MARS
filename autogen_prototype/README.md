# MARS — AutoGen Prototype

**Conversational multi-agent architecture using AutoGen's SelectorGroupChat.**

> **Status: In Progress** — Architecture is defined; end-to-end pipeline verification is ongoing. See [Roadmap](../README.md#roadmap).

This prototype implements the same MARS research pipeline using AutoGen 0.4.x. Instead of a fixed workflow, four specialized agents discuss freely in a shared group chat, with the next speaker selected dynamically based on context.

---

## Architecture

```
User Input (CLI / API)
        │
        ▼
┌─────────────────────────────────────────────┐
│           ResearchSession (Orchestration)    │
│  ┌─────────────────────────────────────────┐ │
│  │       SelectorGroupChat (AutoGen)       │ │
│  │                                         │ │
│  │  ResearchPlanner ←→ Coder              │ │
│  │       ↕              ↕                  │ │
│  │    Critic ←→ Executor                   │ │
│  │                                         │ │
│  │  [Custom speaker selection logic]       │ │
│  └─────────────────────────────────────────┘ │
│       │              │              │        │
│  ┌────┴────┐  ┌──────┴──────┐  ┌───┴───┐   │
│  │ LanceDB │  │ CodeExecutor│  │MsgBus │   │
│  │  (RAG)  │  │             │  │       │   │
│  └─────────┘  └─────────────┘  └───────┘   │
│                      │                       │
│              ┌───────┴───────┐               │
│              │  JSONL Logger │               │
│              └───────────────┘               │
└─────────────────────────────────────────────┘
        │
        ▼
  Artifacts (report, code, logs)
```

### Agents

| Agent | Role | Tools |
|-------|------|-------|
| **ResearchPlanner** | Research strategy, direction setting | LanceDB search/store |
| **Coder** | Python code authoring, experiment implementation | LanceDB search |
| **Critic** | Critical review of plans, code, and results | — |
| **Executor** | Code execution, environment management | Code execution, shell commands |

### Key characteristics

- **General-purpose design** — not tied to a specific research domain
- **Per-agent LLM mapping** — each agent can use a different LLM model
- **Dynamic conversation** — no pre-defined workflow; the next speaker is selected based on conversation context
- **Standard JSONL logging** — all conversations and tool calls logged in a shared event format

---

## Prerequisites

- Python 3.10+
- At least one LLM API key (OpenAI, Anthropic, or Google)

**Optional (advanced features):**
- **RabbitMQ** — async message passing between agents (falls back to in-memory mode)
- **OpenHands** — isolated code execution environment (falls back to local subprocess)

---

## Setup

```bash
cd autogen_prototype

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate      # Linux/macOS
# venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Open .env and add your API key(s)
```

---

## Environment Variables

```env
# ===== LLM API Keys =====
OPENAI_API_KEY=sk-your-openai-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here
GOOGLE_API_KEY=your-google-api-key-here

# ===== Optional =====
# RabbitMQ (falls back to in-memory if not set)
# RABBITMQ_HOST=localhost
# RABBITMQ_PORT=5672

# OpenHands (falls back to local execution if not set)
# OPENHANDS_API_URL=http://localhost:3000
```

---

## Configuration (`config.yaml`)

Configure per-agent LLM models in `config.yaml`:

```yaml
agents:
  research_planner:
    llm:
      provider: "openai"
      model: "gpt-4o"
  coder:
    llm:
      provider: "anthropic"
      model: "claude-sonnet-4-6"
  critic:
    llm:
      provider: "openai"
      model: "gpt-4o-mini"
  executor:
    llm:
      provider: "openai"
      model: "gpt-4o-mini"
```

| Provider    | Env variable         | Example models                           |
|-------------|---------------------|------------------------------------------|
| `openai`    | `OPENAI_API_KEY`    | `gpt-4o`, `gpt-4o-mini`                 |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`, `claude-opus-4-7`  |
| `google`    | `GOOGLE_API_KEY`    | `gemini-2.5-pro`, `gemini-2.5-flash`    |

---

## Running

### CLI mode

```bash
python main.py run \
  --topic "CIFAR-100 image classification benchmark" \
  --goal "Improve Top-1 accuracy by 2% over ResNet-18 baseline" \
  --domain "Computer Vision" \
  --data-path "./data/cifar100" \
  --max-experiments 3 \
  --time-limit 60
```

### Interactive mode

```bash
python main.py interactive
```

### Streaming mode

```bash
python main.py run \
  --topic "Time series anomaly detection" \
  --goal "Achieve F1-Score ≥ 0.90" \
  --domain "Time Series Analysis" \
  --stream
```

### Full CLI options

```
Options:
  --topic           Research topic (required)
  --goal            Research objective (required)
  --domain          Research domain (required)
  --data-path       Path to dataset
  --data-desc       Dataset description
  --frameworks      Preferred frameworks (comma-separated)
  --max-experiments Maximum number of experiments (default: 3)
  --time-limit      Time limit in minutes (default: 60)
  --output          Output directory (default: ./outputs)
  --stream          Enable streaming mode
  --config          Config file path (default: config.yaml)
```

### API server mode

```bash
python main.py serve --host 0.0.0.0 --port 8000
# Swagger UI: http://localhost:8000/docs
```

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Server status |
| `GET`  | `/health` | Health check |
| `POST` | `/api/research/start` | Start research run (sync) |
| `POST` | `/api/research/stream` | Start research run (SSE streaming) |
| `GET`  | `/api/logs/{run_id}` | Retrieve logs |
| `GET`  | `/api/outputs/{run_id}` | Retrieve artifacts |

---

## Outputs

```
outputs/run_<timestamp>/
├── report.md              # Research report (includes conversation history)
├── generated_code/
│   ├── experiment_1.py
│   └── main_experiment.py # Final experiment code
├── results/
│   └── figures/           # Generated plots
└── workspace/             # Code execution working directory
```

---

## Project Structure

```
autogen_prototype/
├── main.py                  # Entry point (CLI + FastAPI)
├── config.yaml              # Per-agent LLM mapping
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── planner.py           # ResearchPlanner agent
│   ├── coder.py             # Coder agent
│   ├── critic.py            # Critic agent
│   └── executor.py          # Executor agent
│
├── core/
│   ├── config_loader.py
│   ├── llm_factory.py
│   ├── chat_manager.py      # GroupChat management and speaker selection
│   ├── message_bus.py       # RabbitMQ / in-memory message bus
│   ├── research_session.py  # Research session orchestration
│   └── logger.py            # Standard JSONL logger
│
├── tools/
│   ├── lance_search.py      # LanceDB vector search
│   └── code_executor.py     # Code executor
│
└── tests/
```

---

## Troubleshooting

**"API key not set"** — Verify the correct API key is set in `.env` for the provider used in `config.yaml`.

**"ModuleNotFoundError"** — Re-run `pip install -r requirements.txt`.

**"RabbitMQ connection failed"** — Expected if RabbitMQ is not running; the system falls back to in-memory mode automatically. Confirm in `config.yaml`:
```yaml
rabbitmq:
  enabled: false
```

**"LanceDB no results"** — The knowledge store is empty on first run; agents populate it automatically via the `add_knowledge` tool.

**Conversation ends too early** — Increase `max_rounds` in `config.yaml`:
```yaml
group_chat:
  max_rounds: 30
```
