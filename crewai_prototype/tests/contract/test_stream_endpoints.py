"""Basic stream endpoint smoke tests for the V2 API."""

from __future__ import annotations

import asyncio

import httpx

from api.app import create_app
from entrypoints.init import initialize_runtime
from runtime.models import RunEvent, RunSession


def _get(app, path: str) -> httpx.Response:
    async def _request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)

    return asyncio.run(_request())


def _seed_terminal_run(services, run_id: str = "run_terminal_001") -> None:
    session_id = "session_terminal_001"
    services.session_store.create(
        RunSession(
            run_id=run_id,
            session_id=session_id,
            research_topic="Terminal stream replay",
            status="completed",
            output_path=str(services.output_root / run_id),
            metadata={"agents": ["Research Planner"]},
        )
    )
    services.event_store.append(
        run_id,
        RunEvent(
            run_id=run_id,
            session_id=session_id,
            event_type="SYSTEM_END",
            content="Run completed.",
            metadata={"status": "completed"},
        ),
    )


def test_stream_endpoint_returns_404_for_unknown_run(tmp_path):
    services = initialize_runtime(project_root=tmp_path)
    app = create_app(services)

    response = _get(app, "/api/v1/research/unknown-run/stream")
    assert response.status_code == 404


def test_artifact_stream_endpoint_returns_404_for_unknown_run(tmp_path):
    services = initialize_runtime(project_root=tmp_path)
    app = create_app(services)

    response = _get(app, "/api/v1/research/unknown-run/artifacts/stream")
    assert response.status_code == 404


def test_stream_endpoint_emits_end_for_terminal_session(tmp_path):
    services = initialize_runtime(project_root=tmp_path)
    _seed_terminal_run(services)
    app = create_app(services)

    response = _get(app, "/api/v1/research/run_terminal_001/stream")
    assert response.status_code == 200
    assert "event: end" in response.text
    assert '"status": "completed"' in response.text


def test_artifact_stream_endpoint_emits_end_for_terminal_session(tmp_path):
    services = initialize_runtime(project_root=tmp_path)
    _seed_terminal_run(services)
    app = create_app(services)

    response = _get(app, "/api/v1/research/run_terminal_001/artifacts/stream")
    assert response.status_code == 200
    assert "event: end" in response.text
    assert '"status": "completed"' in response.text
