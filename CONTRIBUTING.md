# Contributing to MARS

Thank you for your interest in contributing! MARS is an active research project,
so contributions that improve pipeline reliability, add new framework backends,
or extend the benchmark suite are especially welcome.

## Ways to Contribute

| Type | Examples |
|------|----------|
| **Bug fixes** | Pipeline phase failures, SSE streaming edge cases, UI regressions |
| **New framework backend** | AutoGen or LangGraph implementation of the 5-phase pipeline |
| **Benchmark tasks** | New task types (NLP, time series) with evaluation scripts |
| **Documentation** | ADR additions, DEVLOG entries, API spec updates |
| **UI improvements** | New event renderers, accessibility, mobile layout |

## Development Setup

### Backend

```bash
cd crewai_prototype
conda create -n mars python=3.11 -y
conda activate mars
pip install -r requirements.txt
cp .env.example .env   # add your API key
python -m uvicorn entrypoints.api:app --port 8000 --reload
```

### Frontend

```bash
cd research_system_ui
pnpm install
pnpm dev
```

## Project Structure

Before contributing, read the [Architecture doc](docs/ARCHITECTURE.md) and skim
the relevant [ADRs](docs/decisions/) — they explain *why* the code is structured
the way it is, not just *what* it does.

Key files for each phase:

| Phase | File |
|-------|------|
| Phase 0 (workspace) | `crewai_prototype/phases/phase0_workspace.py` |
| Phase 1 (planning) | `crewai_prototype/phases/phase1_planning.py` |
| Phase 2 (coding) | `crewai_prototype/phases/phase2_coding.py` |
| Phase 3 (execution) | `crewai_prototype/phases/phase3_execution.py` |
| Phase 4 (paper) | `crewai_prototype/phases/phase4_writing.py` |
| HitL gates | `crewai_prototype/orchestration/approval_registry.py` |
| Event streaming | `crewai_prototype/runtime/event_store.py` |

## Coding Guidelines

- **No silent failures.** Every phase must emit an event when it fails. The
  `GuidanceGate` / approval gate pattern is the standard escalation path.
- **JSON handoffs between phases.** Never pass raw text between agents — use the
  typed models in `core/handoff_models.py`.
- **Direct LLM calls for code generation.** Do not use CrewAI `Crew.kickoff()`
  for Phase 2 file writing. See [ADR-001](docs/decisions/ADR-001-direct-llm-calls.md).
- **Absolute imports only** in generated code. See [ADR-009](docs/decisions/ADR-009-generated-code-import-rules.md).

## Pull Request Process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Keep PRs focused — one logical change per PR.
3. If your change affects pipeline behavior, add or update the relevant ADR in
   `docs/decisions/`.
4. Run the L1-A API tests against a live server before submitting.
5. Update `CHANGELOG.md` under the `[Unreleased]` section.

## Reporting Issues

Use [GitHub Issues](https://github.com/BluePinetree/mars/issues). Include:
- Which phase failed (0–4)
- The relevant events from `runs/<run_id>/events.jsonl`
- Your `config.yaml` agent LLM mapping (redact API keys)

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).
