# ADR-003 — SSE over WebSocket for Event Streaming

**Date:** 2026-05-10  
**Status:** Accepted  
**Context:** `crewai_prototype/entrypoints/api.py`, `research_system_ui/client/src/lib/api.ts`

---

## Context

MARS runs multi-minute agent pipelines (Phase 0–4 can take 10–60 minutes end-to-end).
The frontend needs to display real-time progress: which phase is active, what each
agent is doing, stdout from the experiment process, token budget, error alerts, and
human-in-the-loop gate triggers (approval dialog, guidance drawer).

The system must push events from the FastAPI backend to the React frontend as they
occur, without polling.

Two standard options for server-push in web applications:
1. **Server-Sent Events (SSE)** — unidirectional, HTTP/1.1+ native, text protocol
2. **WebSocket** — bidirectional, requires upgrade handshake, binary or text

---

## Problem

The interaction pattern in MARS is almost entirely **server → client**:

```
Backend pipeline                    Frontend
  emit("PHASE_START", ...)    ──▶   update Phase stepper
  emit("AGENT_MESSAGE", ...)  ──▶   append to log view
  emit("exec_stdout", ...)    ──▶   update TerminalPane
  emit("PLAN_AWAITING_APPROVAL") ─▶ show ApprovalDialog
```

The only client → server messages are the human-in-the-loop responses
(approve / reject / guidance hint / context injection). These are discrete,
low-frequency, and already have their own REST endpoints
(`POST /api/v1/runs/{run_id}/approve`, `POST /api/v1/runs/{run_id}/guidance`).

Using WebSocket for this pattern would add bidirectionality that the design does not
need, along with the following concrete costs:

| Concern | WebSocket | SSE |
|---|---|---|
| Protocol upgrade | Requires `ws://` / `wss://` + `Upgrade` header | Plain HTTP — no special handling |
| Proxy / firewall compatibility | Many corporate proxies block or mangle WebSocket upgrades | Works transparently over HTTP/1.1 and HTTP/2 |
| Automatic reconnect | Must be implemented manually | Browser `EventSource` reconnects automatically with `Last-Event-ID` |
| CORS | Requires separate CORS configuration for WS | Shares the same CORS rules as REST endpoints |
| FastAPI integration | Requires `websockets` package, explicit `WebSocket` route | Native `StreamingResponse` + `text/event-stream` content type |
| Client library | Requires `ws` npm package or `WebSocket` API with manual reconnect logic | `EventSource` is a W3C standard built into every browser |

---

## Decision

**Use Server-Sent Events (SSE) for all backend → frontend event streaming.**

**Backend** (`api.py`):

```python
@app.get("/api/v1/research/{run_id}/stream")
async def stream_events(run_id: str):
    async def generate():
        cursor = 0
        while True:
            events = event_store.get_events(run_id, since=cursor)
            for event in events:
                cursor = event.sequence + 1
                yield f"id: {event.sequence}\ndata: {json.dumps(event.dict())}\n\n"
            if session_store.is_terminal(run_id):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.3)
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

**Frontend** (`api.ts`):

```typescript
export function subscribeToStream(runId: string, onEvent: (e: LogEvent) => void) {
  const source = new EventSource(`/api/v1/research/${runId}/stream`);
  source.onmessage = (e) => onEvent(JSON.parse(e.data));
  source.addEventListener('end', () => source.close());
  return () => source.close();   // cleanup handle
}
```

**Event persistence:** Every emitted event is appended to
`outputs/{run_id}/events.jsonl` before being streamed. On page reload, the frontend
fetches the full history from `GET /api/v1/research/{run_id}/events` (reads the
`.jsonl` file) and re-renders the log. The SSE cursor (`Last-Event-ID`) then picks
up from where the stream left off.

This gives **exactly-once delivery semantics** without a message broker: events are
durable (on disk), and the stream is resumable.

---

## Consequences

**Positive**

- **Zero extra dependencies.** `StreamingResponse` ships with FastAPI/Starlette.
  `EventSource` is in every modern browser.
- **Transparent proxy compatibility.** The pipeline targets research environments
  where corporate firewalls and university proxies are common. HTTP works everywhere.
- **Free reconnect.** If the browser tab is backgrounded and the connection drops,
  `EventSource` reconnects automatically. The `since=cursor` parameter on the server
  ensures no events are missed.
- **HitL gates are REST, not stream.** The approval / guidance responses are
  synchronous `POST` requests. Keeping them out of the stream avoids any ordering
  ambiguity between stream events and gate responses.
- **Log replay on refresh.** The event-store pattern (append `.jsonl`, serve on
  demand) makes browser refresh a first-class scenario with no extra engineering.

**Negative / Trade-offs**

- **HTTP/1.1 connection limit.** Browsers enforce a maximum of 6 concurrent HTTP/1.1
  connections per origin. Running many simultaneous sessions in separate tabs could
  exhaust the limit. Mitigated by HTTP/2 multiplexing (supported by uvicorn with
  `--ssl` or behind nginx).
- **Text-only payload.** SSE is text-based. Binary artifacts (images, model checkpoints)
  cannot be streamed inline. These are served as separate static file endpoints.
- **No server → client backpressure.** SSE does not surface when the client is slow.
  Event bursts (e.g. rapid `exec_stdout` lines) are buffered in the `StreamingResponse`
  generator and delivered as fast as the client reads. This has not been a problem in
  practice (terminal output is human-readable speed).

---

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **WebSocket** | Bidirectionality not needed; adds proxy/CORS complexity; manual reconnect required |
| **Long polling** | Higher latency (poll interval delay); more server load; harder to implement streaming output |
| **GraphQL subscriptions** | Requires a GraphQL layer on top of a REST API; significant additional complexity |
| **Redis Pub/Sub + WebSocket** | Adds a stateful external service (Redis); overkill for a single-server deployment |

---

## Related

- `crewai_prototype/entrypoints/api.py` — SSE route, event store
- `crewai_prototype/runtime/event_store.py` — `.jsonl` persistence
- `research_system_ui/client/src/lib/api.ts` — `subscribeToStream()`
- [DEVLOG](../DEVLOG.md) — event normalization bug (2026-05-28)
