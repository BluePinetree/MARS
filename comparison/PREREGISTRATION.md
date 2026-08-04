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
| `epoch_cap` | **20** | Measured: ResNet-18 55.2 s/epoch, MobileNetV2 98.2 s/epoch on CIFAR-10. A CIFAR-adapted stem (§4.2) keeps 32×32 feature maps through the first stage instead of 8×8 and is expected to raise per-epoch cost by roughly 2–3×; 20 epochs × 2 models then lands near 2 h, fitting 3 rollouts per task inside the submission window |
| `experiment_timeout_s` | **10800** (3 h) | Covers the above with margin. The previous CrewAI value (5400 s) would have killed a 30-epoch two-model vision run; AutoGen (300 s) and LangGraph (600 s) could not have completed any vision run at all |
| `wall_clock_cap_s` per rollout | **14400** (4 h) | Hard kill, includes LLM phases |
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

### 3.1 Model and temperature

All frameworks use the **same model assignment**: `gpt-5.2` for planning / design / code generation /
analysis / writing, `gpt-5-mini` for execution reporting.

Temperature is **declared identically across frameworks**, with one conditional resolved in advance:

- Intended: identical per-role temperature for all three frameworks.
- Measured state at v1: CrewAI applies its configured temperatures; AutoGen deliberately omits
  temperature on GPT-5 paths (documented in `core/llm_factory.py` as an API constraint); LangGraph
  configures temperatures but never passes them.
- **Decision rule, fixed now:** if the model API accepts an explicit temperature, all three
  frameworks pass the same per-role values. If it does not, **all three omit temperature** and the
  provider default is used uniformly. Whichever branch is taken is reported, and the actual applied
  value per framework is recorded in each run record.

This is a commitment to uniformity, not to a specific number, because the number is contingent on a
provider constraint that must be verified rather than assumed.

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

Literature SOTA is **not** usable as a threshold. CIFAR-10 ResNet-18 reaches ~94.9% only at 200–250
epochs; the epoch cap in §3 is 20. A SOTA threshold would make qualification impossible regardless
of agent behaviour, and would measure the budget rather than the agent.

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
| v1 | *(this commit)* | Initial: §1–§7 frozen; tabular thresholds set; vision threshold procedure set |
| v2 | pending | Vision threshold values from reference baseline run |
