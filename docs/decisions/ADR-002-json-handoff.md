# ADR-002 — JSON-Structured Handoffs Between Agents

**Date:** 2026-05-15  
**Status:** Accepted  
**Context:** `crewai_prototype/core/handoff_models.py`, all `phases/` modules

---

## Context

In a multi-agent pipeline, each phase produces output that becomes the input of the
next phase. MARS has five phases involving six distinct agent roles
(Planner, Designer, Coder, Executor, Analyzer, Writer). The key design question is:
**what format should the handoff payload take?**

Two natural options exist:
1. **Free-form text transcript** — pass the prior agent's full LLM response forward.
2. **Structured JSON schema** — parse the prior response into a typed model and pass
   that model to the next stage.

---

## Problem

Free-form transcript hand-offs are common in simple demo pipelines but create several
compounding problems at production scale:

| Problem | Impact |
|---|---|
| **Context accumulation** | Each phase appends to a growing transcript. By Phase 4 the context window is dominated by Phase 1–3 logs irrelevant to writing. |
| **Extraction ambiguity** | Downstream agents must re-parse upstream prose, introducing a second failure mode: "did the LLM correctly extract the metric name from the previous response?" |
| **No schema enforcement** | A missing field from Planner (e.g. `recommended_profile`) silently produces a wrong Design, which silently produces wrong Code. The error surfaces at Phase 3 execution — three phases later. |
| **UI cannot render it** | The frontend needs structured data (file list, success criteria, metrics) to populate `ApprovalDialog`, `ProposalSheet`, etc. Raw text cannot be rendered as a structured component. |
| **Token cost** | Full transcripts passed forward double or triple the token cost of each phase. |

---

## Decision

**All inter-phase handoffs use Pydantic models serialized as JSON.**

Each phase defines its output as a Pydantic model:

```python
# core/handoff_models.py
class PlannerResult(BaseModel):
    problem_statement: str = ""
    research_questions: list[str] = []
    hypotheses: list[str] = []
    success_criteria: list[str] = []
    constraints: list[str] = []
    risks: list[dict] = []
    recommended_profile: str = "generic_script"
    next_stage_inputs: dict[str, str] = {}

class DesignerResultV4(BaseModel):
    experiment_family: str = ""
    entry_point: str = "src/main.py"
    files: list[FileNodeSpec] = []
    generation_order: list[str] = []
    stage_assignments: dict[str, int] = {}
    import_graph: dict[str, list[str]] = {}

class PlanBundle(BaseModel):      # Phase 1 → Phase 2 handoff
    planner: PlannerResult
    designer: DesignerResultV4
    workspace: WorkspaceConfig
```

**Extraction rule:** Each agent is prompted to output *only* a JSON object matching
the target schema. A `json_extractor.extract_json_object()` utility parses the LLM
response, then `model.model_validate(data)` enforces the schema with defaults for
any missing optional fields.

**Persistence rule:** Every handoff JSON is written to `outputs/{run_id}/handoff/`
before the next phase starts. If the pipeline crashes mid-run, the checkpoint can be
read back to resume without re-running completed phases.

---

## Consequences

**Positive**

- **Early failure detection.** `model_validate()` raises a validation error the moment
  a required field is absent, at the phase boundary — not three phases later.
- **Zero context accumulation.** Each phase prompt contains only the fields it actually
  needs from upstream, not a full transcript.
- **Frontend can render structured data.** `ApprovalDialog` reads `plan.files`,
  `plan.planner.success_criteria`, `plan.planner.constraints` directly from the JSON
  payload sent over SSE.
- **Checkpoint / resume.** JSON files on disk are the natural resume point after a crash.
- **Testability.** Each phase can be unit-tested by constructing a valid input model
  and asserting on the output model — no mock conversation history needed.

**Negative / Trade-offs**

- **LLM must output valid JSON.** Occasionally an LLM wraps the JSON in prose
  (`"Here is the plan: {...}"`). The `extract_json_object()` utility handles this
  with a regex scan for the first `{`, but malformed JSON still requires a retry.
- **Schema maintenance.** Adding a new field to a handoff model requires updating
  the corresponding prompt and all downstream consumers.
- **Verbosity in prompts.** Each agent's task description includes the full JSON
  schema it must produce, adding ~100–200 tokens per call.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| LangChain `OutputParser` | Still requires the LLM to produce parseable text; adds a dependency without solving the schema-enforcement problem |
| Shared vector-store memory (e.g. ChromaDB) | Introduces a stateful external service; overkill for a sequential pipeline where phase order is deterministic |
| Python `dataclass` instead of Pydantic | No built-in JSON validation / coercion; `model_validate` from Pydantic is significantly more robust |
| Passing file paths only | Would work for large artifacts (logs, code) but not for the structured plan data the UI needs to render |

---

## Related

- `crewai_prototype/core/handoff_models.py` — all handoff model definitions
- `crewai_prototype/core/json_extractor.py` — `extract_json_object()` implementation
- `crewai_prototype/phases/phase1_planning.py` — writes `planner_result.json`, `designer_result.json`
- `crewai_prototype/CLAUDE.md` — "Stable Conventions" section
