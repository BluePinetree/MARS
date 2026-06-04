# ADR-004 — Staged Code Generation with Dependency Injection

**Date:** 2026-05-21  
**Status:** Accepted  
**Context:** `crewai_prototype/phases/phase2_coding.py`, `crewai_prototype/core/handoff_models.py`

---

## Context

Phase 2 generates a workspace of Python source files from a Designer-produced file
tree. A typical experiment workspace contains 4–8 files with real inter-file
dependencies: a config module, data loaders that import the config, a model module
that imports the config, and a main entry point that imports everything.

The question is: in what order should these files be generated, and what context
should the LLM receive when generating each one?

---

## Problem

A naive approach generates all files independently or in an arbitrary order.
This produces two failure modes:

1. **Signature mismatch** — `datasets.py` calls `get_dataloaders(config, split='train')`
   but `config.py` exports `Config` with no `split` parameter. Neither file knows the
   other's actual API, so the LLM invents one. Cross-module `TypeError` at runtime.

2. **Import errors on first run** — `main.py` imports from `trainer.py` which imports
   from `models.py`. If `models.py` is generated after `main.py`, the LLM cannot
   know what `models.py` will export, and may generate an incompatible import.

These failures are not reliably caught by syntax checks. They surface only at
execution time (Phase 3), requiring a costly round-trip back to Phase 2.

---

## Decision

**Generate files in dependency order, injecting the actual content of already-written
dependency files into each subsequent prompt.**

The Designer assigns each file a *stage*:

| Stage | Rules | Examples |
|-------|-------|---------|
| **1** — Config / Utils | No imports from other mutable files | `config.py`, `constants.py` |
| **2** — Data / Model / Trainer | May import Stage-1 files only | `datasets.py`, `models.py`, `trainer.py` |
| **3** — Entry Point | May import Stages 1 and 2 | `main.py` |

Within each stage, files are generated in the order produced by the Designer's
`generation_order` list (topological order within the stage).

**Dependency injection:** When generating a Stage-2 file, the prompt includes the
full source of every Stage-1 file it imports. When generating Stage-3, the prompt
includes all Stage-1 and Stage-2 files it depends on. The LLM therefore sees the
*actual exported symbols* — not a speculative description — and generates
call-compatible code.

```python
# phase2_coding.py — _build_dep_context()
def _build_dep_context(imports_from: list[str], workspace_root: str) -> str:
    for dep_path in imports_from:
        raw = (Path(workspace_root) / dep_path).read_text()
        sections.append(f"# === {dep_path} ===\n{raw}")
    # hard cap: _MAX_DEP_CHARS per file, _MAX_TOTAL_DEP_CHARS total
```

The prompt template makes the contract explicit:

```
Workspace dependencies (already written; your imports must match their actual exports):
# === src/config.py ===
<actual source>
```

---

## Consequences

**Positive**

- **Cross-module signature compatibility.** The LLM generates `from config import Config`
  only after seeing what `Config` actually looks like. Signature mismatches drop
  from ~40 % of runs to near zero.
- **Repair loop efficiency.** When repairs are needed, the repair prompt also
  injects dependency content, giving the LLM complete information.
- **Stage isolation.** Stage-1 files have no mutable imports — they can be generated
  and verified independently. A Stage-1 failure does not block Stage-2 generation.
- **Designer quality feedback.** If the Designer assigns wrong stage numbers, the
  injection fails predictably (dependency file not yet written). This surfaces
  Designer errors early, in Phase 2, rather than at execution time.

**Negative / Trade-offs**

- **Prompt size grows with dependencies.** A Stage-3 entry point whose prompt
  includes 3 Stage-2 files (each 200 lines) uses significantly more tokens.
  Mitigated: `_MAX_DEP_CHARS = 6,000` per file, `_MAX_TOTAL_DEP_CHARS = 18,000`
  total — dependency content is truncated with a note about the truncation.
- **Generation order matters.** If the Designer produces a wrong topological order,
  a dependency file may not exist yet. The `_build_dep_context()` function skips
  missing files silently; this is intentional (partial context is better than
  generation failure).
- **Stage assignments are LLM-generated.** The Designer is an LLM agent and can
  assign wrong stages. Stage rules are included in the Designer's task description
  and `DesignerResultV4` schema validation catches structural violations.

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Generate all files simultaneously** | No cross-file context; high signature mismatch rate |
| **Provide the full design spec (responsibility + exports list) without source** | LLM interprets "exports: get_dataloaders" differently from seeing `def get_dataloaders(config: Config, split: str = 'train') → DataLoader:`. Actual source is more precise. |
| **Generate all files, then repair cross-module errors in a second pass** | Cascading repairs are expensive; a cross-module bug in Stage 1 requires re-generating all downstream stages |
| **Static analysis to extract symbols before generation** | Would require the generated file to exist first — circular dependency |

---

## Related

- [ADR-001](ADR-001-direct-llm-calls.md) — Direct LLM calls (the mechanism that makes dependency injection possible — the full file source is injected into a single LLM prompt, not passed as a tool argument)
- `crewai_prototype/phases/phase2_coding.py` — `_build_dep_context()`, `run_coding_phase()`
- `crewai_prototype/core/handoff_models.py` — `FileNodeSpec.stage`, `DesignerResultV4.generation_order`
- `crewai_prototype/phases/phase1_planning.py` — Designer stage assignment rules
