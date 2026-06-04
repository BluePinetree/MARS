# Run Summary — ResNet-18 vs MobileNetV2 on CIFAR-10

| Field | Value |
|-------|-------|
| **Run ID** | `0910b073c843` |
| **Status** | completed |
| **Phases completed** | 0, 1, 2, 3, 4 |
| **Total events** | 96 |
| **Paper quality** | 1.00 |
| **Coherence score** | 0.74 |
| **Total repair attempts** | 1 (Phase 2 auto-repair) |

## Pipeline Timeline

```
Phase 0  Workspace setup + Preflight Q&A (4 questions)          ~40s
Phase 1  Planning (Planner → Designer) + Human approval gate    ~70s
Phase 2  Staged code generation (19 files, 3 stages)            ~3m 30s
         └─ 1 import error auto-repaired (runner.py)
Phase 3  Experiment execution (attempt 1)                        ~8s
Phase 4  Paper writing (7 sections + coherence revision)         ~2m 40s
         └─ Abstract + Experiments revised (coherence score 0.74)
```

## Generated Files (Phase 2)

Stage 1 — Config & Utilities:
`exp_config.py`, `seed.py`, `time_utils.py`, `json_io.py`, `metrics.py`,
`constants.py`, `datasets_cifar10.py`

Stage 2 — Model & Training:
`models.py`, `optim.py`, `engine.py`, `runner.py`

Stage 3 — Entry Point:
`main.py`

## Human-in-the-Loop Gates Used

1. **Preflight** — 4 questions answered (dataset constraints, compute, eval metric, extra context)
2. **Plan Approval** — approved after ~70s deliberation

## Extension Proposals Generated (Phase 4)

1. Run with a different random seed to verify reproducibility.
2. Ablation study: disable one component at a time to measure individual contribution.
3. Test on a held-out dataset to evaluate generalization.
