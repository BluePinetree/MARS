# MARS Benchmark Pre-Registration — v1

**Status:** v1 (rules and tabular thresholds frozen; vision thresholds pending v2)
**Committed:** see `git log` for this file. The commit timestamp is the evidence of ordering.
**Applies to:** all MARS benchmark runs executed after the v2 commit.

---

## 0. Purpose and binding scope

This document fixes, **before any benchmark run is executed**, how success is defined and how
models are selected. It exists so that thresholds cannot be adjusted after seeing results.

Two commitments follow from that:

1. **No MARS benchmark run is executed until v2 of this file is committed.** All runs that predate
   it are archived under `crewai_prototype/legacy_pre_prereg/` and are reported only as
   *preliminary / pre-registration* evidence, never as primary results.
2. **Any later change to this file must be a separate, visible commit** with a stated reason.
   Silent edits defeat the purpose.

### Why v1 and v2

Vision thresholds are derived from a human-written reference baseline that has not yet been run
(§4.2). v1 therefore freezes the **procedure** for obtaining those numbers; v2 fills in the numbers
that the procedure mechanically produces. This is the same construction MLE-bench uses: the medal
threshold *rule* is fixed in advance and the *values* are read off an external leaderboard.

| Version | Freezes |
|---|---|
| **v1** (this file) | §1–§7 in full, including tabular threshold values and the vision threshold procedure |
| **v2** | §4.2 vision threshold values, filled in from the reference baseline run |

---

## 1. Task set

| ID | Task | Type | Dataset | Primary metric | Higher is better |
|---|---|---|---|---|---|
| T1 | Titanic survival | tabular classification | seaborn titanic | ROC-AUC | yes |
| T2 | California Housing | tabular regression | `sklearn.datasets.fetch_california_housing` | R² | yes |
| T3 | CIFAR-10 | vision classification | CIFAR-10 | top-1 accuracy | yes |

**CIFAR-100 is excluded from the pre-registered set.** Measured cost is 361 s/epoch for the two-model
comparison (ResNet-50 233.5 s + ViT-tiny 127.9 s on an RTX A6000); at the epoch cap in §3 this
exceeds the compute available in the submission window. Existing CIFAR-100 evidence remains
available as preliminary material. It may be added to a later round without changing §2–§6.

---

## 2. Measurement protocol

### 2.1 Trials

Each (framework, task) pair receives **3 independent agent rollouts**. A rollout is a complete
pipeline execution from the same natural-language topic and goal. Rollouts differ only in the
agent's own non-determinism (planning, code generation); the experiment seed is fixed (§3).

We report the distribution across rollouts. Rollout-to-rollout variance is the dominant observed
source of spread in preliminary data (16–23 percentage points on CIFAR-10 top-1 at fixed seed and
fixed epoch count) and is therefore the variance this protocol estimates.

**Limitation, stated in advance:** experiment-seed variance is not separately estimated in this
round (`repeats = 1`, §3). LLM sampling is not seed-controllable through the providers used, so
rollout non-determinism cannot be eliminated, only measured.

### 2.1a Task brief given to the agent (frozen verbatim)

Every framework receives the **byte-identical** topic and goal string. The goal states protocol
requirements and task requirements; it never states an implementation.

**T3 goal (frozen):**

> Train and compare ResNet-18 and MobileNetV2 on CIFAR-10 and report top-1 accuracy for each.
> Adapt each architecture to the 32×32 input resolution (do not downsample the input excessively
> before the first residual stage). Hold out 10% of the training data as a validation set; use the
> validation set alone for epoch selection and model selection, and evaluate the test set exactly
> once at the end. Report per-model test top-1 accuracy, the selected epoch, and training time.

**What this is and is not.** *"Adapt each architecture to the 32×32 input resolution"* is a
requirement, of the kind a supervisor writes in a brief. It is deliberately **not** an
implementation: the goal does not say "replace the 7×7 stride-2 convolution with 3×3 stride-1 and
remove the max-pool". The agent must still work out and write the change.

**Why the requirement is stated rather than withheld.** Two conditions were available:

| Condition | Brief contains | Measures |
|---|---|---|
| **C1 — adopted** | protocol requirements + architecture requirement | whether the agent implements a correct brief |
| C2 — not adopted for this round | task only | whether the agent knows unprompted that 32×32 needs an adapted stem |

C2 measures tacit knowledge, which is interesting but is a property of the underlying model, not of
the orchestration framework — so it would very likely produce the same failure in all three
frameworks and would not discriminate between them, which is what this benchmark exists to do.
Preliminary data supports that: MobileNetV2 was stem-adapted in **0 of 3** rollouts.

**C2 evidence is reported from existing data rather than re-measured.** The three preliminary
CIFAR-10 rollouts were produced under a C2-style brief and are reported as a separate finding —
that the agent applied the well-documented ResNet CIFAR-stem adaptation in 2 of 3 rollouts but never
applied the less-documented MobileNetV2 stride adaptation. No new compute is spent on C2.

**Reporting rule.** Numbers produced under C1 are never presented as if they came from a brief that
withheld the requirement. The goal string above is reproduced in the paper.

### 2.2 Validation and test discipline

- Each rollout must split a validation set out of the **training** data.
- **All selection — epoch selection, model selection, hyperparameter choice — uses validation only.**
- The held-out test set is evaluated **once**, after selection is final.
- Across the 3 rollouts, the rollout with the best **validation** metric is selected; its **test**
  metric is the reported quality figure (§2.4).

Test data must not influence any decision. A run that selects on test is a protocol violation and
is excluded from primary results with the reason recorded.

### 2.3 Reliability metrics (primary)

Two tiers, evaluated per (framework, task):

**Tier 1 — execution reliability**

| Metric | Definition |
|---|---|
| `execution pass@3` | ≥1 of 3 rollouts completed execution without error |
| `execution pass-all-3` | 3 of 3 rollouts completed execution without error |

**Tier 2 — qualified reliability (PRIMARY)**

A rollout is a **Qualified Success** iff **both** hold:
1. execution completed successfully, **and**
2. the rollout's test metric meets the task threshold in §4.

| Metric | Definition |
|---|---|
| **`Qualified pass@3`** | ≥1 of 3 rollouts is a Qualified Success |
| **`Qualified pass-all-3`** | 3 of 3 rollouts are Qualified Successes |

`Qualified pass@3` and `Qualified pass-all-3` are the **primary reliability metrics** of this
benchmark. Tier 1 is reported alongside so that "ran but produced an unusable result" is visible
rather than absorbed into a completion rate.

### 2.4 Quality metric (primary)

For each (framework, task): select the rollout with the best **validation** metric, then report its
**held-out test** metric. This single number is the **primary quality metric**.

### 2.5 Secondary metrics

Reported for completeness, not used for ranking:

- Per-rollout metric distribution (all 3 values), mean, and range
- Wall-clock time per rollout; phase-level timings
- Repair attempts, split by stage (codegen / execution / paper revision)
- Improvement-loop iterations and epoch budget actually consumed
- Human gate events opened (this benchmark runs headless; see §6.3)
- Failure classification (§5)
- Token counts and cost **where instrumentation exists** (§7, open limitation)

### 2.6 Success determination is made by the harness, not the agent

`execution_success`, `validation_tier`, `dataset_origin`, and `evaluation_scope` are written by the
**agent-generated code** and are therefore self-reported. They are recorded but are **not** the
success signal.

Qualified Success is determined by an independent verifier (`comparison/verify.py`) reading
`result.json`. The verifier rejects a rollout when:

- `result.json` is absent
- no domain metric is present
- all domain metric values are NaN / None / non-numeric
- notes contain a stub/placeholder marker (`smoke implementation`, `not yet implemented`,
  `placeholder`) or metrics contain only placeholder keys (e.g. `smoke_metric`)

Preliminary data motivating this: of 21 runs self-reporting `execution_success = true`, 11 passed
independent verification. Self-reported and verified success rates differed by a factor of 1.9.

---

## 3. Compute and interaction budget

Identical for all frameworks and all tasks unless stated. Values are grounded in measured
per-epoch cost on the target machine (RTX A6000).

| Parameter | Value | Basis |
|---|---|---|
| `epoch_cap` | **200** | The standard training length reported for CIFAR-10 in the literature (~93–95% top-1 for ResNet-18 at 200–250 epochs). A short cap would make the published band unreachable by construction and would measure the budget rather than the agent |
| `experiment_timeout_s` | **43200** (12 h) | Measured, not estimated — see §3.3. The pre-registered recipe costs **22.1 s/epoch** for the two-model pair (ResNet-18 9.14 s + MobileNetV2 12.96 s, including a per-epoch validation pass), i.e. **1.23 h for 200 epochs**. A deliberately unoptimised implementation (`num_workers=0`, `batch_size=32`) measures 107.2 s/epoch for the pair → 5.96 h. The cap therefore carries ~2× margin over the slow case, because throughput depends on code the agent writes. The previous CrewAI value (5400 s) killed a real 200-epoch attempt three times (run `a917380da3a6`, 2026-06-15); AutoGen (300 s) and LangGraph (600 s) could not complete any vision run at all |
| `wall_clock_cap_s` per rollout | **54000** (15 h) | Hard kill, includes LLM phases and repair loops (~3 h budgeted on top of `experiment_timeout_s`) |
| `stall_timeout_s` | **3600** (1 h) | Kill the process tree if the experiment produces no output for this long. **Raising `experiment_timeout_s` without this converts "dies at 90 minutes" into "hangs for 12 hours."** The longest legitimate silent gap is one epoch (≤13 s at the recipe throughput, ≤100 s unoptimised) plus first-epoch dataset preparation, so 1 h is ~30× the worst legitimate gap |
| `epoch_cap` enforcement | **harness-injected and harness-verified** | No framework enforces an epoch budget today. CrewAI derives it from the agent's own plan (`phases/phase3_execution.py` `_planned_epochs`); AutoGen and LangGraph have no epoch plumbing at all. The harness injects `--epochs {epoch_cap}` into every experiment command, and the verifier of §2.6 rejects any rollout whose `result.json` `actual_epochs` does not match. Placing the check outside all three frameworks keeps it symmetric, for the same reason the success criterion is placed there (§3.2). `planned_epochs` is recorded so that what the agent *wanted* stays visible |
| `max_improvement_iterations` | **1** | Disables within-rollout epoch escalation. Only CrewAI implements such a loop; leaving it on would measure engineering investment rather than framework. Model selection is performed by the 3-rollout protocol in §2.2 instead |
| `max_codegen_repair_attempts` | **5** | CrewAI's existing value; adopted for all |
| `max_execution_repair_attempts` | **3** | CrewAI's existing value; adopted for all |
| `max_replan_rounds` | **5** | CrewAI's existing value; adopted for all |
| `max_coder_llm_turns` | **40** | LangGraph's existing coder value; AutoGen's default of 1 tool iteration and 30 conversation rounds cannot write a multi-file workspace |
| `max_conversation_rounds` | **120** | For conversation-driven frameworks (AutoGen) |
| `experiment_seed` | **42** | Fixed |
| `repeats` (within-rollout seed repeats) | **1** | See §2.1 limitation |
| `val_split` | **0.1** of training data | Fixed |
| `device` | `cuda` for T3, `cpu` for T1/T2 | Per task, identical across frameworks |
| `cost_cap_usd` | **not enforced** | No token accounting exists yet (§7) |

### 3.3 Cost calibration (measured 2026-08-05, before any benchmark run)

Budget values in §3 are derived from measurement on the target machine, not from estimates.
Artifacts: `comparison/calibration/` (scripts + raw JSON). Environment: python 3.10.19,
torch 2.5.0+cu118, NVIDIA RTX A6000.

Recipe under test = the recipe of §4.2 (SGD lr 0.1 / momentum 0.9 / wd 5e-4, cosine T_max=200,
batch 128, `num_workers=8`, `cudnn.deterministic=True`, no AMP, CIFAR-adapted stems on both models,
45 000/5 000 train/val split, per-epoch validation pass).

| Model | s/epoch (train + val) | `total_stride` | LR schedule active |
|---|---|---|---|
| ResNet-18 (CIFAR stem) | **9.14** | 8 (final 4×4) | yes |
| MobileNetV2 (CIFAR stem) | **12.96** | 8 (final 4×4) | yes |
| **pair** | **22.10** | | |

| Projection | Value |
|---|---|
| 200 epochs, one rollout (both models) | **1.23 h** |
| 9 rollouts (3 frameworks × 3) | **11.05 h** |
| 9 rollouts + reference baseline | **12.28 h** |

Three findings from calibration changed the budget, and are recorded because they contradict
plausible assumptions:

1. **The CIFAR stem adaptation is nearly free in wall-clock terms.** It raises multiply-accumulate
   count ~15× (37.0 → 555.4 MMACs for ResNet-18 at 32×32), but measured epoch time rose only ~10%
   at `num_workers=0`. Per-epoch cost was bound by single-process data loading, not by the GPU.
   Budget arithmetic that multiplied a measured epoch time by a "stem factor" therefore
   double-counted, and the earlier 20-epoch cap was justified by that error.
2. **`num_workers=8` with `batch_size=128` is the dominant lever**: 107.2 → 22.1 s/epoch for the
   pair (4.9×). This is why 200 epochs is affordable at all.
3. **Mixed precision plus `channels_last` makes MobileNetV2 slower** (13.94 → 16.41 s/epoch), a
   known regression pattern for depthwise convolutions, so neither is used. Consequently
   `cudnn.deterministic=True` is retained at no throughput cost — determinism is not traded away
   for speed, which supports the reproducibility tiers of §6.2.

### 3.1 Model and temperature

All frameworks use the **same model assignment**: `gpt-5.2` for **every** LLM-backed role.
`gpt-5-mini` is not used. Rationale: CrewAI never instantiates an executor LLM
(`experiment_executor` is declared in `config.yaml` but has no call site — verified by enumerating
every `create_llm_for_agent` caller), so assigning a smaller model to that role would create an LLM
call that one framework makes and another does not. A single model also removes model as a possible
confound with framework.

**Sampling parameters are not sent by any framework.** The v1 conditional is resolved to the "omit"
branch:

- `temperature`, `top_p`, `top_k`, `presence_penalty`, `frequency_penalty` are **not sent** on any
  request by any framework.
- Evidence for taking this branch:
  1. `gpt-5.2` accepts an explicit `temperature` **only** when `reasoning_effort` is `none` (its
     default). At any higher effort the API rejects it.
  2. `gpt-5-mini` / `gpt-5-nano` / `gpt-5` / `gpt-5.2-pro` reject any `temperature` other than the
     default.
  3. Therefore "identical explicit per-role temperature across frameworks" is unreachable, and
     achieving it for `gpt-5.2` alone would require permanently pinning `reasoning_effort=none` —
     i.e. benchmarking a reasoning-disabled configuration. That changes what is being measured, so
     it is not an acceptable way to satisfy a parameter-uniformity requirement.
- Measured state at v1, recorded because it contradicts what the configuration files suggest:
  CrewAI **was** sending its configured temperatures (verified offline by assembling the request
  payload without contacting the provider: the OpenAI provider's `_prepare_responses_params` emits
  `{'input', 'model', 'temperature'}`, and its only special case is an `o1`-model check that
  `gpt-5.2` does not match). Those requests succeeded solely because CrewAI sends no
  `reasoning_effort`. AutoGen omitted temperature deliberately; LangGraph configured temperatures
  into an object that is never constructed at runtime. A record of *declared* configuration would
  have shown all three as compliant.

**`reasoning_effort` is an explicit pre-registered parameter.** Omitting temperature removes the
constraint that previously pinned effort to `none`, so effort must be stated rather than inherited:

| Parameter | Value | Basis |
|---|---|---|
| `reasoning_effort` | **`medium`** | Sent explicitly by all three frameworks. Leaving it unsent resolves to `none`, which is uniform only by accident and silently breakable; and benchmarking a reasoning model with reasoning off would not represent the system under study |
| `temperature` / `top_p` / `top_k` | **not sent** | See above |

Because `medium` differs from the effort under which all preliminary CrewAI runs were produced
(`none`, by default), preliminary latency and token figures are **not** continuous with this
round's and are not compared across the change.

The parameter set actually placed on the wire is recorded per rollout (§6.1) and asserted equal
across frameworks by an offline parity check that makes no API calls (§6.4).

### 3.2 Reliability defences are a controlled variable

CrewAI currently carries roughly 1,750 lines of reliability machinery (stub/NaN rejection,
cross-module signature gate, scaffold contract, repair guards); AutoGen has ~173 and LangGraph ~121.
Comparing under that asymmetry measures engineering investment, not orchestration style.

For this benchmark round, the verifier in §2.6 runs **outside** all three frameworks, at harness
level, so the success criterion is identical for every framework. Remaining in-framework asymmetry
is reported as a limitation with per-framework defence-code line counts.

---

## 4. Thresholds

A rollout's test metric must **meet or exceed** the threshold to qualify (§2.3).

### 4.1 Tabular — frozen in v1

| Task | Metric | Threshold | Basis |
|---|---|---|---|
| T1 Titanic | ROC-AUC | **≥ 0.83** | Upper end of the standard textbook baseline band (0.77–0.83) for this dataset; reachable by a competent logistic-regression or tree baseline |
| T2 California Housing | R² | **≥ 0.78** | Just above the measured untuned gradient-boosting result (0.7756) and at the lower end of the commonly reported 0.80–0.85 band, so a default-hyperparameter fit alone does not qualify |

Literature/textbook bands are usable here because the standard performance range for these datasets
is well established and does not depend on a training-budget choice.

### 4.2 Vision — procedure frozen in v1, values set in v2

Literature SOTA is **not** usable as a threshold, but the reason is not budget mismatch — at the
§3 cap of 200 epochs the published ~93–95% band is within reach. A published number is unusable
because it was not produced under this protocol: published figures do not fix our validation split
(§3, 10% carved out of train), our evaluate-test-once discipline (§2.2), our seed, or our exact stem
adaptation, and they are frequently selected on the test set. A threshold taken from a paper would
therefore fold protocol differences into the qualification decision.

The human-written reference baseline removes that confound: same architectures, same stem
adaptation, same budget, same split, same seed, same select-on-validation / evaluate-test-once
discipline. The only difference is that a human wrote the code — which is the contrast this
benchmark exists to measure.

**Threshold tolerance: `baseline_test_top1 − 2.00 pp`, per model.**

The tolerance is not a convenience margin; it is the observed spread between competent human
implementations of the same recipe on the same model. Published CIFAR-10 ResNet-18 results under
the §4.2 recipe range from **93.02%** (kuangliu/pytorch-cifar) to **95.4%**
(HF `jaeunglee/resnet18-cifar10-unlearning`) — a **2.4 pp** band. A tolerance narrower than that
band would fail agents for landing inside the range of normal human variation, which measures
nothing about orchestration. 2.00 pp is set just inside the observed band.

**The threshold is per model, not per rollout best.** A rollout qualifies only if **both**
ResNet-18 and MobileNetV2 clear their own thresholds. Taking the best model would let a rollout
qualify while one arm of the comparison is broken — and that failure mode is already observed:
across three preliminary CIFAR-10 rollouts, ResNet-18 was stem-adapted in 2 of 3 but MobileNetV2 in
**0 of 3**, so a best-model rule would have passed rollouts whose headline comparison was invalid.

**Procedure (frozen):**

1. Apply the CIFAR stem adaptation to the model definitions used by the reference baseline:
   replace the 7×7 stride-2 convolution with 3×3 stride-1 and remove the initial max-pool, so that
   32×32 inputs are not downsampled to 8×8 before the first residual stage. This is standard
   practice for CIFAR and its absence suppresses accuracy for architectural rather than agent-related
   reasons.
2. Run a **human-written reference baseline** for T3 under the **identical budget of §3**
   (epoch cap 20, seed 42, same device, same val split, selection on validation, single test
   evaluation).
3. The baseline's **test top-1 accuracy** becomes the T3 threshold, recorded to two decimal places.
4. The baseline's source, command, and result path are recorded in v2 alongside the number.
5. The baseline is run **once**. It is not re-run to obtain a more convenient threshold.

| Task | Metric | Threshold | Set in |
|---|---|---|---|
| T3 CIFAR-10 | top-1 accuracy | *(reference baseline value)* | **v2** |

---

## 5. Failure handling

All rollouts are reported, including failures. Failures are classified into three mutually exclusive
classes:

| Class | Meaning | Counted in reliability metrics? |
|---|---|---|
| `agent_failure` | The agent produced a plan, code, or result that failed | **Yes** |
| `infra_failure` | Provider authentication, rate limiting, network unavailability | **No** — excluded, count reported separately |
| `harness_bug` | Defect in MARS orchestration itself, not in agent output | **No** — excluded, count reported separately |

Excluding infrastructure failures follows MLE-bench practice; excluded runs are never imputed and
their count is always shown.

Failure types recorded within `agent_failure`:
`planning_drift`, `design_mismatch`, `syntax_error`, `import_error`, `signature_mismatch`,
`runtime_error`, `timeout`, `missing_result`, `schema_error`, `repair_loop_exhausted`,
`fake_success_stub`, `fake_success_nan`, `paper_without_result`, `protocol_violation_test_selection`.

`signature_mismatch` and `paper_without_result` are included because they were the two most frequent
signatures in preliminary data (13 of 21 result-bearing runs, and 16 runs respectively) and were
absent from earlier taxonomy drafts.

---

## 6. Reproducibility recording

### 6.1 Per-run record

Every rollout emits a record containing: `run_id`, `framework`, `task_id`, `trial_id`,
`experiment_seed`, applied `model_assignment` and temperature, the full `budget` block of §3,
`pipeline_status`, harness-determined `task_outcome`, `self_reported` block (isolated, §2.6),
`primary_metric`, flat metrics, telemetry, failure classification, and a reproducibility block with
`python_version`, package versions, `requirements_hash`, `commit`, `worktree_dirty`,
`entry_command`, and `experiment_replay_command`.

`commit` and `worktree_dirty` are recorded automatically. Results produced from a dirty working tree
are labelled as such.

### 6.2 Reproducibility tiers

| Tier | Meaning |
|---|---|
| `T0_logs_only` | Artifacts and logs retained; no environment pin |
| `T1_env_pinned` | Environment and command recorded sufficiently to attempt re-execution |
| `T2_replay_verified` | A frozen-workspace re-execution was performed and its diff recorded |

`T2` requires an actual replay artifact pair. Self-declared replay equality without a diff record
does not qualify. Verified replays are stored as `replay_diff_<task>.json`.

### 6.3 Human interaction

Benchmark rollouts run headless: the preflight, plan-approval, and guidance gates are auto-resolved
by the harness so that the measurement is of autonomous behaviour. Event logs therefore show gates
**opened** but no human decision content. Records state this explicitly; gate-opened counts are
reported as an autonomy indicator, and no run in this benchmark may be described as human-approved.

---

## 7. Known limitations, declared in advance

1. **No token or cost accounting.** LLM call counts, token usage, and cost are not collected for
   CrewAI; the shared telemetry module records zeros. Cost-per-qualified-success cannot be reported
   this round. Instrumentation is planned but is not retroactive.
2. **LLM sampling is not seed-controlled.** The providers used offer no reproducible sampling.
   Rollout non-determinism is measured (§2.1), not removed.
3. **`tool_calls` is not comparable across frameworks.** CrewAI performs file I/O in orchestrator
   Python by design; other frameworks delegate it to LLM tool calls. The count is an artefact of
   architecture, so it is reported qualitatively only.
4. **In-framework reliability defences remain asymmetric** (§3.2), mitigated by harness-level
   verification but not eliminated.
5. **Single machine, single hardware profile.** No cross-hardware generalisation is claimed.
6. **Three tasks, three rollouts.** Small sample. Per-rollout raw values are published; no
   significance testing is performed.
7. **Frameworks other than CrewAI have no prior completed run.** If a framework fails to produce any
   qualified success, that is reported as the result, not treated as a missing measurement.

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| v1 | 2026-08-04 | Initial: §1–§7 frozen; tabular thresholds set; vision threshold procedure set |
| v1.1 | 2026-08-05 | `epoch_cap` 20 → **200** (literature standard, user decision). §3 budget re-derived from measurement (§3.3 added: 22.1 s/epoch for the model pair; timeout 3 h → 12 h; `stall_timeout_s` added; harness-level epoch enforcement specified). §3.1 resolved to the sampling-omit branch with `reasoning_effort=medium` and a single model (`gpt-5.2`) for all roles. §4.2 threshold tolerance set to **−2.00 pp per model**, justified by the 2.4 pp spread between published human implementations, and made per-model rather than best-model. §2.1a added: the T3 brief is frozen verbatim under condition **C1** (protocol + architecture requirements stated, implementation withheld); C2 is reported from existing data only |
| v2 | pending | Vision threshold values from the reference baseline run |

> No MARS benchmark rollout has been executed under this protocol at the time of the v1.1 commit.
> The reference baseline has not been run. Calibration runs (§3.3) train for 3 epochs to measure
> cost only, produce no benchmark result, and are not rollouts.
