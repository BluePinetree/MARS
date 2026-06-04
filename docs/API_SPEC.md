# API Specification — MARS Backend (v1)

**Base URL:** `http://localhost:8000`  
**Protocol version:** `v1`  
**Authentication:** None (local service)  
**Content-Type:** `application/json` (unless noted)

> Interactive docs: `http://localhost:8000/docs` (Swagger UI) · `http://localhost:8000/redoc` (ReDoc)

---

## Table of Contents

1. [Research Runs](#1-research-runs)
2. [Session Management](#2-session-management)
3. [Human-in-the-Loop Interaction](#3-human-in-the-loop-interaction)
4. [Artifacts](#4-artifacts)
5. [Diagnostics](#5-diagnostics)
6. [SSE Event Reference](#6-sse-event-reference)
7. [Data Models](#7-data-models)
8. [Error Responses](#8-error-responses)

---

## 1. Research Runs

### `POST /api/v1/research`

Create and immediately start a new research pipeline run.

**Request body**

```json
{
  "topic": "CIFAR-10 ResNet-18 vs ViT-tiny accuracy comparison",
  "goal": "Compare top-1 accuracy and parameter efficiency over 10 epochs",
  "domain": "Computer Vision",
  "data_path": "/datasets/cifar10",
  "data_description": "Pre-downloaded CIFAR-10 in torchvision cache format",
  "workspace_path": null,
  "frameworks": ["PyTorch"],
  "constraints": ["max 2 GPU hours", "batch size ≤ 128"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | `string` | ✅ | Research question (min 1 char) |
| `goal` | `string` | — | Elaboration of the research goal |
| `domain` | `string` | — | Domain hint (e.g. `"Computer Vision"`, `"NLP"`) |
| `data_path` | `string` | — | Absolute local path or URL to the dataset |
| `data_description` | `string` | — | Human-readable dataset description passed to the Planner |
| `workspace_path` | `string` | — | Override the output directory (default: `outputs/{run_id}/`) |
| `frameworks` | `string[]` | — | Preferred ML frameworks |
| `constraints` | `string[]` | — | Additional hard constraints for the Planner |

**Response `200 OK`**

```json
{
  "run_id": "run_a1b2c3d4",
  "session_id": "run_a1b2c3d4",
  "status": "queued"
}
```

**Errors:** `422` validation error (empty topic) · `409` duplicate run · `503` coordinator unavailable

---

### `GET /api/v1/research/{run_id}/status`

Return the current normalized status snapshot for a run.

**Response `200 OK`**

```json
{
  "run_id": "run_a1b2c3d4",
  "session_id": "run_a1b2c3d4",
  "research_topic": "CIFAR-10 ResNet-18 vs ViT-tiny",
  "status": "running",
  "progress": 0.42,
  "current_phase": 2,
  "started_at": "2026-06-01T10:00:00Z",
  "ended_at": null,
  "error": null,
  "agents": ["Planner", "Designer", "Coder"],
  "total_events": 87
}
```

| Field | Description |
|-------|-------------|
| `status` | `"queued"` \| `"running"` \| `"completed"` \| `"failed"` \| `"paused"` |
| `progress` | 0.0–1.0 estimate based on phase completion |
| `current_phase` | 0–4, derived from the last `PHASE_START` event |

**Errors:** `404` unknown run_id

---

### `GET /api/v1/research/{run_id}/result`

Return the final result summary (meaningful after `status = "completed"` or `"failed"`).

**Response `200 OK`**

```json
{
  "run_id": "run_a1b2c3d4",
  "status": "completed",
  "output_path": "/app/outputs/run_a1b2c3d4",
  "result_summary": { "accuracy": 0.912, "epochs": 10 },
  "error": null
}
```

**Errors:** `404` unknown run_id

---

### `GET /api/v1/research/{run_id}/stream`

**SSE stream** — push all log events in real-time as they are emitted by the pipeline.

**Response headers**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**SSE frame format**

```
id: 42
data: {"run_id":"run_a1b2c3d4","session_id":"run_a1b2c3d4","event_type":"AGENT_MESSAGE","content":"[Planner] Plan ready","timestamp":"2026-06-01T10:01:23Z","agent_name":"Planner","metadata":{"round":1}}

```

Each frame carries one serialized `RunEvent`. See [§6 SSE Event Reference](#6-sse-event-reference) for the full event type taxonomy.

**Terminal frame** — emitted once when the run ends:

```
event: end
data: {}

```

The client should close the `EventSource` on receiving `event: end`.

**Resume after disconnect:** The `id` field in each frame is the event sequence number. Pass `Last-Event-ID: {n}` in the reconnect request to receive only events after sequence `n`.

**Errors:** `404` unknown run_id

---

## 2. Session Management

### `GET /api/v1/sessions`

List all known sessions, newest first.

**Query parameters**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `50` | Maximum number of sessions |

**Response `200 OK`** — array of status objects (same shape as `/research/{run_id}/status`)

---

### `GET /api/v1/sessions/{run_id}/logs`

Return all stored log events for a session. Used for full log replay after a page refresh.

**Response `200 OK`** — array of `RunEvent` objects

```json
[
  {
    "run_id": "run_a1b2c3d4",
    "session_id": "run_a1b2c3d4",
    "event_type": "SYSTEM_START",
    "timestamp": "2026-06-01T10:00:00Z",
    "agent_name": null,
    "content": "Research pipeline started.",
    "metadata": {}
  }
]
```

**Errors:** `404` unknown run_id

---

### `DELETE /api/v1/sessions/{run_id}`

Delete session metadata from the session store.

> **Note:** This removes the session record only. It does **not** cancel a running pipeline.
> Call `DELETE /api/v1/runs/{run_id}` first to stop an active run.

**Response `200 OK`**

```json
{ "deleted": true }
```

**Errors:** `404` unknown run_id

---

## 3. Human-in-the-Loop Interaction

These endpoints are called by the UI to resolve pipeline gates. The pipeline thread
blocks on the gate until one of these endpoints is called or the gate times out.

---

### `POST /api/v1/runs/{run_id}/approve`

Resolve the **Phase 1 plan approval gate**.

**Request body**

```json
{
  "action": "approve",
  "feedback": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | `"approve"` \| `"reject"` \| `"modify"` | ✅ | User decision |
| `feedback` | `string` | conditional | Required for `"reject"` and `"modify"` |

**Behavior by action**

| Action | Pipeline result |
|--------|----------------|
| `"approve"` | Pipeline immediately proceeds to Phase 2 |
| `"modify"` | Planner + Designer re-run with `feedback` injected; `PLAN_AWAITING_APPROVAL` is emitted again (up to `MAX_REPLAN_ROUNDS = 5`) |
| `"reject"` | Pipeline terminates; session transitions to `status = "failed"` |

**Response `200 OK`**

```json
{
  "run_id": "run_a1b2c3d4",
  "action": "approve",
  "message": "Plan approved successfully."
}
```

**Errors:** `404` no active approval gate for this run (may have already been resolved, or run hasn't reached Phase 1 yet)

---

### `GET /api/v1/runs/{run_id}/approval_status`

Check whether Phase 1 is currently waiting for plan approval.

**Response `200 OK` — no gate**

```json
{ "run_id": "run_a1b2c3d4", "awaiting_approval": false }
```

**Response `200 OK` — gate active**

```json
{
  "run_id": "run_a1b2c3d4",
  "awaiting_approval": true,
  "plan": {
    "planner": {
      "problem_statement": "Compare ResNet-18 and ViT-tiny on CIFAR-10.",
      "research_questions": ["Which architecture converges faster?"],
      "success_criteria": ["top-1 accuracy > 0.85 within 10 epochs"],
      "constraints": ["max 2 GPU hours"],
      "risks": [{ "risk": "OOM on ViT", "mitigation": "reduce batch size to 64" }],
      "recommended_profile": "vision_classification"
    },
    "designer": {
      "files": [
        {
          "path": "src/datasets.py",
          "responsibility": "Load and preprocess CIFAR-10",
          "exports": ["get_dataloaders"],
          "imports_from": ["src/config.py"],
          "stage": 2,
          "mutable": true
        }
      ],
      "entry_point": "src/main.py",
      "generation_order": ["src/config.py", "src/datasets.py", "src/main.py"]
    },
    "workspace": { "run_id": "run_a1b2c3d4", "workspace_dir": "..." }
  }
}
```

The `plan` field contains the full `PlanBundle` used to populate `ApprovalDialog`.

---

### `POST /api/v1/runs/{run_id}/guidance`

Resolve a **Phase 2 or Phase 3 guidance gate**, triggered when automated repair
exceeds `MAX_AUTO_REPAIR_ATTEMPTS` on a single file.

**Request body**

```json
{
  "file_path": "src/models.py",
  "user_action": "provide_fix",
  "hint": "Use nn.BatchNorm2d after each conv layer."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_path` | `string` | ✅ | Relative path of the stuck file |
| `user_action` | `string` | ✅ | See table below |
| `hint` | `string` | conditional | Required for `"provide_fix"` |

**`user_action` values**

| Value | Behavior |
|-------|----------|
| `"continue"` | Reset attempt counter and retry with no hint |
| `"provide_fix"` | Retry with `hint` injected into the repair prompt |
| `"skip"` | Write a minimal stub for this file and continue to the next |
| `"manual_edit"` | Pipeline pauses; user edits the file manually; pipeline re-runs checks |

**Response `200 OK`**

```json
{
  "run_id": "run_a1b2c3d4",
  "file_path": "src/models.py",
  "user_action": "provide_fix",
  "message": "Guidance received. Pipeline repair loop will resume."
}
```

**Errors:** `404` no active guidance gate for this run/file

---

### `GET /api/v1/runs/{run_id}/guidance_status`

Check whether Phase 2/3 is currently waiting for user guidance.

**Response `200 OK` — no gate**

```json
{ "run_id": "run_a1b2c3d4", "awaiting_guidance": false }
```

**Response `200 OK` — gate active**

```json
{
  "run_id": "run_a1b2c3d4",
  "awaiting_guidance": true,
  "file_path": "src/models.py",
  "error": "ImportError: No module named 'timm'\n  File 'src/models.py', line 3",
  "attempts": 5,
  "options": ["continue", "skip", "provide_fix", "manual_edit"]
}
```

`error` is capped at the last 500 characters of the traceback.

---

### `DELETE /api/v1/runs/{run_id}`

Send a cancellation signal to a running pipeline.

The pipeline checks for cancellation at safe checkpoints between phase steps.
The session transitions to `status = "failed"` once cancellation is processed.

**Response `200 OK`**

```json
{ "run_id": "run_a1b2c3d4", "message": "Cancellation signal sent." }
```

**Errors:** `404` run not found or already in a terminal state

---

## 4. Artifacts

### `GET /api/v1/research/{run_id}/artifacts/content?path={path}`

Return the text content of a specific artifact file within the run's output directory.

**Query parameters**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `path` | ✅ | Absolute or run-relative path to the artifact |

**Example**

```
GET /api/v1/research/run_a1b2c3d4/artifacts/content?path=src/models.py
GET /api/v1/research/run_a1b2c3d4/artifacts/content?path=paper/report.md
```

**Response `200 OK`** — `text/plain` file content

**Security:** Paths are resolved against the run's `output_path`. Requests for paths
outside the run directory return `400 Bad Request`.

**Errors:** `400` path outside run directory · `404` run or file not found

---

### `GET /api/v1/research/{run_id}/artifacts/stream`

**SSE stream** — push artifact update events as files are created or modified.

Same frame format as the log stream. Useful for watching generated code files
appear in real-time during Phase 2.

---

## 5. Diagnostics

### `GET /api/v1/contract`

Return the official endpoint list and protocol version. Called by the frontend on
startup to verify API compatibility.

**Response `200 OK`**

```json
{
  "version": "v1",
  "protocol": "sse",
  "official": true,
  "deprecated_protocols": ["websocket"],
  "endpoints": [
    "POST /api/v1/research",
    "GET /api/v1/research/{run_id}/status",
    "GET /api/v1/research/{run_id}/result",
    "GET /api/v1/research/{run_id}/stream",
    "GET /api/v1/research/{run_id}/artifacts/content",
    "GET /api/v1/research/{run_id}/artifacts/stream",
    "GET /api/v1/sessions",
    "GET /api/v1/sessions/{run_id}/logs",
    "DELETE /api/v1/sessions/{run_id}",
    "GET /api/v1/contract",
    "GET /api/v1/providers",
    "GET /api/v1/runtime-diagnostics"
  ]
}
```

---

### `GET /api/v1/providers`

Return currently available LLM providers, determined by which API keys are set.

**Response `200 OK`**

```json
{ "providers": ["anthropic", "openai"] }
```

---

### `GET /api/v1/runtime-diagnostics`

Return backend runtime information for debugging and deployment verification.

**Response `200 OK`**

```json
{
  "pipeline_version": "v3-crewai-native",
  "project_root": "/app/crewai_prototype",
  "output_root": "/app/outputs",
  "python_executable": "/usr/bin/python3"
}
```

---

## 6. SSE Event Reference

All events emitted on the stream endpoint share the same `RunEvent` envelope.
The `event_type` field determines how the frontend renders the event.

### Event envelope

```typescript
interface RunEvent {
  run_id:     string;
  session_id: string;
  event_type: string;           // see table below
  timestamp:  string;           // ISO-8601 UTC
  agent_name: string | null;
  content:    string | null;    // human-readable message shown in the log view
  metadata:   Record<string, unknown>;
}
```

### Event type taxonomy

| Event type | Phase | UI component | Key `metadata` fields |
|------------|-------|--------------|-----------------------|
| `SYSTEM_START` | 0 | `SystemBanner` (blue) | — |
| `SYSTEM_END` | 4 | `SystemBanner` (green/red) | `elapsed_secs`, `status` |
| `PHASE_START` | any | Phase stepper → active | `phase: 0–4`, `round?` |
| `PHASE_COMPLETE` | any | Phase stepper → done | `phase: 0–4` |
| `AGENT_THINKING` | any | `AgentMessage` (dimmed) | `agent_tag` |
| `AGENT_MESSAGE` | any | `AgentMessage` | `agent_tag`, `action?` |
| `TOOL_CALL` | any | `ToolCall` card | `tool_name`, `args` |
| `TOOL_RESULT` | any | `ToolResult` card | `tool_name`, `success` |
| `FILE_GENERATION_START` | 2 | Log entry | `file_path`, `stage` |
| `FILE_GENERATED` | 2 | `FileGenerated` card | `file_path`, `stage`, `lines` |
| `FILE_SYNTAX_ERROR` | 2 | `FileError` card (red) | `file_path`, `error`, `line?` |
| `FILE_IMPORT_ERROR` | 2 | `FileError` card (red) | `file_path`, `error` |
| `FILE_FIXED` | 2 | `FileFix` card (green) | `file_path`, `attempt` |
| `SMOKE_TEST_START` | 2 | Log entry | — |
| `SMOKE_TEST_DONE` | 2 | `SmokeTest` card | `passed: bool`, `error?` |
| `PLAN_AWAITING_APPROVAL` | 1 | `ApprovalDialog` (modal) | `plan`, `round`, `timeout_secs` |
| `USER_GUIDANCE_NEEDED` | 2, 3 | `GuidanceDrawer` (sheet) | `file_path`, `error`, `attempts` |
| `USER_GUIDANCE_RECEIVED` | 2, 3 | — (closes drawer) | `file_path`, `user_action` |
| `PREFLIGHT_QUESTION` | 0 | `PreflightFlow` (fullscreen) | `questions: string[]` |
| `PREFLIGHT_ANSWERED` | 0 | — (closes preflight) | `answers: {}` |
| `token_budget_snapshot` | 2 | `TokenBudgetBar` | `files_done`, `total_files`, `pct` |
| `token_budget_warning` | 2 | `TokenBudgetBar` (amber) | `pct`, `warning_msg` |
| `exec_stdout` | 3 | `TerminalPane` | `line`, `stream: "stdout"\|"stderr"` |
| `failure_escalation` | 3 | `FailureAlert` (red banner) | `pattern`, `count`, `details` |
| `SECTION_DRAFT_DONE` | 4 | `SectionDraft` card | `section_name`, `quality_score` |
| `extension_proposals` | 4 | `ProposalSheet` (bottom sheet) | `proposals: string[]` |
| `EXPERIMENT_RESULT` | 3 | `ExperimentResult` card | `metrics: {}` |

### `PLAN_AWAITING_APPROVAL` — `metadata` detail

```json
{
  "run_id": "run_a1b2c3d4",
  "round": 1,
  "timeout_secs": 3600,
  "plan": {
    "planner": {
      "problem_statement": "...",
      "research_questions": ["..."],
      "hypotheses": ["..."],
      "success_criteria": ["accuracy > 0.85"],
      "constraints": ["max 2 GPU hours"],
      "risks": [{ "risk": "OOM on ViT", "mitigation": "reduce batch size" }],
      "recommended_profile": "vision_classification",
      "next_stage_inputs": {}
    },
    "designer": {
      "experiment_family": "image_classification",
      "entry_point": "src/main.py",
      "files": [ { "path": "src/config.py", "stage": 1, "mutable": true, "exports": ["Config"], "imports_from": [] } ],
      "generation_order": ["src/config.py", "src/datasets.py", "src/models.py", "src/main.py"],
      "stage_assignments": { "src/config.py": 1, "src/datasets.py": 2, "src/main.py": 3 }
    }
  }
}
```

### `USER_GUIDANCE_NEEDED` — `metadata` detail

```json
{
  "run_id": "run_a1b2c3d4",
  "file_path": "src/models.py",
  "error": "SyntaxError: unexpected EOF while parsing\n  File 'src/models.py', line 47",
  "attempts": 5
}
```

### `token_budget_snapshot` — `metadata` detail

```json
{
  "files_done": 3,
  "total_files": 5,
  "pct": 60
}
```

### `exec_stdout` — `metadata` detail

```json
{
  "line": "Epoch 3/10 — loss: 0.432, acc: 0.812",
  "stream": "stdout"
}
```

### `extension_proposals` — `metadata` detail

```json
{
  "proposals": [
    "Extend to CIFAR-100 with 100-class head and top-5 accuracy metric",
    "Add data augmentation (RandAugment) and compare effect on both architectures",
    "Profile inference latency on CPU vs GPU for deployment comparison"
  ]
}
```

---

## 7. Data Models

### `RunSession`

```typescript
interface RunSession {
  run_id:          string;
  session_id:      string;
  research_topic:  string;
  research_goal:   string | null;
  research_domain: string | null;
  status:          "queued" | "running" | "completed" | "failed" | "paused";
  started_at:      string;          // ISO-8601 UTC
  ended_at:        string | null;
  output_path:     string | null;   // absolute server-side path to outputs/{run_id}/
  error:           string | null;
  result_summary:  unknown | null;
  metadata:        Record<string, unknown>;
}
```

### `RunEvent`

```typescript
interface RunEvent {
  run_id:     string;
  session_id: string;
  event_type: string;
  timestamp:  string;           // ISO-8601 UTC
  agent_name: string | null;
  content:    string | null;
  metadata:   Record<string, unknown>;
}
```

### `ResearchRequest`

```typescript
interface ResearchRequest {
  topic:            string;         // required, min 1 char
  goal?:            string;
  domain?:          string;
  data_path?:       string;
  data_description?: string;
  workspace_path?:  string;
  frameworks?:      string[];
  constraints?:     string[];
}
```

### `ApproveRequest`

```typescript
interface ApproveRequest {
  action:    "approve" | "reject" | "modify";
  feedback?: string;   // required for reject / modify
}
```

### `GuidanceRequest`

```typescript
interface GuidanceRequest {
  file_path:   string;
  user_action: "continue" | "skip" | "provide_fix" | "manual_edit";
  hint?:       string;   // required for provide_fix
}
```

---

## 8. Error Responses

All error responses use FastAPI's standard envelope:

```json
{ "detail": "Human-readable error message." }
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request (e.g. artifact path outside run directory) |
| `404` | Resource not found (run_id, session, gate, artifact) |
| `409` | Conflict (duplicate run, or gate already resolved) |
| `422` | Request validation error (missing required field, wrong type) |
| `503` | Service unavailable (coordinator not initialized) |

**`422` example**

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "topic"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```
