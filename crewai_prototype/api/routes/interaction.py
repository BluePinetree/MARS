"""api/routes/interaction.py — User interaction endpoints for V4 pipeline.

These endpoints allow the UI to respond to pipeline events that need human input:
  POST /runs/{id}/approve   — approve, reject, or modify the Phase 1 plan
  POST /runs/{id}/guidance  — provide guidance when Phase 2/3 is stuck
  DELETE /runs/{id}         — cancel a running pipeline
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/runs", tags=["interaction"])


# ── Request models ────────────────────────────────────────────────────────────

class ApproveRequest(BaseModel):
    action: Literal["approve", "reject", "modify"]
    feedback: Optional[str] = None  # required for reject/modify


class GuidanceRequest(BaseModel):
    file_path: str
    user_action: Literal["continue", "skip", "provide_fix", "manual_edit"]
    hint: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{run_id}/approve")
async def approve_plan(run_id: str, payload: ApproveRequest, request: Request) -> dict:
    """Resolve the Phase 1 plan approval gate.

    The pipeline thread is blocked waiting for this endpoint. Calling it
    unblocks the thread and lets the pipeline proceed.
    """
    services = request.app.state.services
    approval_registry = services.approval_registry

    resolved = approval_registry.resolve(
        run_id=run_id,
        action=payload.action,
        feedback=payload.feedback,
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"No active approval gate for run {run_id}. "
                   "The plan may have already been approved or the run has not reached Phase 1.",
        )
    return {
        "run_id": run_id,
        "action": payload.action,
        "message": f"Plan {payload.action}d successfully.",
    }


@router.get("/{run_id}/approval_status")
async def get_approval_status(run_id: str, request: Request) -> dict:
    """Check whether there is an active approval gate for this run."""
    services = request.app.state.services
    gate = services.approval_registry.get(run_id)
    if gate is None:
        return {"run_id": run_id, "awaiting_approval": False}
    return {
        "run_id": run_id,
        "awaiting_approval": True,
        "plan": gate.plan_payload,
    }


@router.post("/{run_id}/guidance")
async def provide_guidance(run_id: str, payload: GuidanceRequest, request: Request) -> dict:
    """Resolve an active guidance gate in Phase 2 or Phase 3.

    The repair loop is blocked waiting for this endpoint. Calling it with
    user_action='continue' and an optional hint unblocks the loop and resets
    the attempt counter. user_action='skip' stubs the file and continues.
    """
    services = request.app.state.services
    guidance_registry = services.guidance_registry

    resolved = guidance_registry.resolve(
        run_id=run_id,
        file_path=payload.file_path,
        user_action=payload.user_action,
        hint=payload.hint or "",
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"No active guidance gate for run={run_id}, file={payload.file_path}.",
        )
    return {
        "run_id": run_id,
        "file_path": payload.file_path,
        "user_action": payload.user_action,
        "message": "Guidance received. Pipeline repair loop will resume.",
    }


@router.get("/{run_id}/guidance_status")
async def get_guidance_status(run_id: str, request: Request) -> dict:
    """Check whether there is an active guidance gate (pipeline waiting for user)."""
    services = request.app.state.services
    result = services.guidance_registry.get_any(run_id)
    if result is None:
        return {"run_id": run_id, "awaiting_guidance": False}
    file_path, gate = result
    return {
        "run_id": run_id,
        "awaiting_guidance": True,
        "file_path": file_path,
        "error": gate.error_msg[-500:],
        "attempts": gate.attempt_count,
        "options": ["continue", "skip", "provide_fix", "manual_edit"],
    }


@router.delete("/{run_id}")
async def cancel_run(run_id: str, request: Request) -> dict:
    """Cancel a running pipeline. The pipeline will stop at the next cancellation check."""
    services = request.app.state.services
    found = services.coordinator.cancel_run(run_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found or already finished.")
    return {"run_id": run_id, "message": "Cancellation signal sent."}
