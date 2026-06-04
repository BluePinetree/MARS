"""orchestration/approval_registry.py — User interaction gates.

Two registries:
  ApprovalRegistry  — blocks the pipeline until the user approves/rejects a plan.
  GuidanceRegistry  — blocks a repair loop until the user provides a hint.

Both use threading.Event so the pipeline thread blocks without touching the
FastAPI event loop. The API layer simply calls .resolve() from an async endpoint.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional


# ── Approval Gate (Plan approval at end of Phase 1) ──────────────────────────

@dataclass
class ApprovalGate:
    """Blocks the pipeline until the user approves, rejects, or modifies the plan."""
    plan_payload: dict                          # serialized PlanBundle
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    action: str = "pending"                     # "approve" | "reject" | "modify"
    feedback: Optional[str] = None              # user's revision instructions

    def wait(self, timeout: float) -> bool:
        """Block until resolved. Returns True if resolved, False on timeout."""
        return self._event.wait(timeout=timeout)

    def resolve(self, action: str, feedback: Optional[str] = None) -> None:
        """Called by API layer. action: 'approve' | 'reject' | 'modify'."""
        self.action = action
        self.feedback = feedback
        self._event.set()

    @property
    def is_approved(self) -> bool:
        return self.action == "approve"

    @property
    def is_rejected_or_modified(self) -> bool:
        return self.action in ("reject", "modify")


class ApprovalRegistry:
    """Thread-safe store of active ApprovalGates keyed by run_id."""

    def __init__(self) -> None:
        self._gates: dict[str, ApprovalGate] = {}
        self._lock = threading.Lock()

    def register(self, run_id: str, gate: ApprovalGate) -> None:
        with self._lock:
            self._gates[run_id] = gate

    def get(self, run_id: str) -> Optional[ApprovalGate]:
        with self._lock:
            return self._gates.get(run_id)

    def resolve(self, run_id: str, action: str, feedback: Optional[str] = None) -> bool:
        """Resolve the gate. Returns False if no gate found."""
        with self._lock:
            gate = self._gates.get(run_id)
        if gate is None:
            return False
        gate.resolve(action, feedback)
        return True

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._gates.pop(run_id, None)


# ── Guidance Gate (repair loop escalation in Phase 2/3) ──────────────────────

@dataclass
class GuidanceGate:
    """Blocks a repair loop until the user provides guidance."""
    file_path: str
    error_msg: str
    attempt_count: int
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    user_action: str = "pending"    # "continue" | "skip" | "provide_fix" | "manual_edit"
    hint: str = ""                  # optional user-provided fix hint

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)

    def resolve(self, user_action: str, hint: str = "") -> None:
        """Called by API layer."""
        self.user_action = user_action
        self.hint = hint
        self._event.set()

    @property
    def should_skip(self) -> bool:
        return self.user_action == "skip"


class GuidanceRegistry:
    """Thread-safe store of active GuidanceGates.

    Key is (run_id, file_path) because multiple files can be stuck simultaneously
    (though in practice only one repair loop runs at a time).
    """

    def __init__(self) -> None:
        self._gates: dict[tuple[str, str], GuidanceGate] = {}
        self._lock = threading.Lock()

    def register(self, run_id: str, file_path: str, gate: GuidanceGate) -> None:
        with self._lock:
            self._gates[(run_id, file_path)] = gate

    def get(self, run_id: str, file_path: str) -> Optional[GuidanceGate]:
        with self._lock:
            return self._gates.get((run_id, file_path))

    def get_any(self, run_id: str) -> Optional[tuple[str, GuidanceGate]]:
        """Return the first active guidance gate for a run (for API listing)."""
        with self._lock:
            for (rid, fpath), gate in self._gates.items():
                if rid == run_id:
                    return fpath, gate
        return None

    def resolve(self, run_id: str, file_path: str, user_action: str, hint: str = "") -> bool:
        with self._lock:
            gate = self._gates.get((run_id, file_path))
        if gate is None:
            return False
        gate.resolve(user_action, hint)
        return True

    def remove(self, run_id: str, file_path: str) -> None:
        with self._lock:
            self._gates.pop((run_id, file_path), None)

    def remove_all(self, run_id: str) -> None:
        with self._lock:
            keys = [(r, f) for (r, f) in self._gates if r == run_id]
            for k in keys:
                del self._gates[k]


# ── Cancellation Token ────────────────────────────────────────────────────────

class CancellationToken:
    """Signals all loops in a run to stop cleanly."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class CancellationRegistry:
    """Thread-safe store of CancellationTokens keyed by run_id."""

    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = threading.Lock()

    def create(self, run_id: str) -> CancellationToken:
        token = CancellationToken()
        with self._lock:
            self._tokens[run_id] = token
        return token

    def cancel(self, run_id: str) -> None:
        with self._lock:
            token = self._tokens.get(run_id)
        if token:
            token.cancel()

    def get(self, run_id: str) -> Optional[CancellationToken]:
        with self._lock:
            return self._tokens.get(run_id)

    def remove(self, run_id: str) -> None:
        with self._lock:
            self._tokens.pop(run_id, None)
