"""Legacy JSONL + WebSocket backend preserved for reference use."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="research_system_ui legacy backend",
    description="Legacy JSONL/WebSocket backend kept for compatibility checks.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_DIR = Path("./outputs")


def get_log_dir() -> Path:
    """Return the configured log root."""
    return LOG_DIR


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _discover_log_files(run_dir: Path) -> list[Path]:
    return sorted(list(run_dir.glob("logs/*.jsonl")) + list(run_dir.glob("*.jsonl")))


def parse_session_info(run_id: str, log_files: list[Path]) -> dict[str, Any] | None:
    """Build a compact session summary from discovered JSONL logs."""
    events: list[dict[str, Any]] = []
    for log_file in log_files:
        events.extend(_load_jsonl(log_file))
    if not events:
        return None

    first_event = events[0]
    last_event = events[-1]
    topic = "Untitled Research"
    for event in events:
        metadata = event.get("metadata")
        if isinstance(metadata, dict) and metadata.get("research_topic"):
            topic = str(metadata["research_topic"])
            break

    raw_status = "running"
    if isinstance(last_event.get("metadata"), dict):
        raw_status = str(last_event["metadata"].get("status", raw_status))

    return {
        "run_id": run_id,
        "session_id": str(first_event.get("session_id", run_id)),
        "research_topic": topic,
        "status": raw_status,
        "total_events": len(events),
        "start_time": first_event.get("timestamp"),
        "end_time": last_event.get("timestamp") if raw_status in {"completed", "failed"} else None,
    }


def discover_sessions() -> list[dict[str, Any]]:
    """Discover sessions from per-run or flat JSONL logs."""
    log_dir = get_log_dir()
    if not log_dir.exists():
        return []

    sessions: list[dict[str, Any]] = []
    for run_dir in sorted(log_dir.iterdir()):
        if run_dir.is_dir():
            info = parse_session_info(run_dir.name, _discover_log_files(run_dir))
            if info:
                sessions.append(info)

    for jsonl_file in sorted(log_dir.glob("*.jsonl")):
        info = parse_session_info(jsonl_file.stem, [jsonl_file])
        if info:
            sessions.append(info)
    return sessions


def get_session_logs(run_id: str) -> list[dict[str, Any]]:
    """Return all JSONL log events for the selected run."""
    log_dir = get_log_dir()
    run_dir = log_dir / run_id
    if run_dir.exists():
        log_files = _discover_log_files(run_dir)
    else:
        log_files = [log_dir / f"{run_id}.jsonl"]

    events: list[dict[str, Any]] = []
    for log_file in log_files:
        events.extend(_load_jsonl(log_file))
    return events


@app.get("/api/v1/sessions")
def api_list_sessions() -> list[dict[str, Any]]:
    """List sessions from JSONL logs."""
    return discover_sessions()


@app.get("/api/v1/sessions/{run_id}/logs")
def api_get_logs(run_id: str) -> list[dict[str, Any]]:
    """Return session logs from JSONL files."""
    return get_session_logs(run_id)


@app.websocket("/ws/v1/sessions/{run_id}/stream")
async def websocket_stream(run_id: str, websocket: WebSocket) -> None:
    """Tail a session log file and forward appended JSONL events."""
    await websocket.accept()
    offset = 0
    try:
        while True:
            events = get_session_logs(run_id)
            for event in events[offset:]:
                await websocket.send_json(event)
            offset = len(events)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Legacy JSONL/WebSocket backend")
    parser.add_argument("--log-dir", default="./outputs", help="Root directory containing run logs")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    return parser.parse_args()


def main() -> None:
    """Run the legacy backend with uvicorn."""
    import uvicorn

    global LOG_DIR
    args = parse_args()
    LOG_DIR = Path(args.log_dir)
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()

