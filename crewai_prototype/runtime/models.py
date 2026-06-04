"""Runtime data models shared by the V2 services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

EVENT_TYPES = (
    "SYSTEM_START",
    "SYSTEM_END",
    "AGENT_THINKING",
    "AGENT_MESSAGE",
    "TOOL_CALL",
    "TOOL_RESULT",
    "FILE_CREATED",
    "CODE_BLOCK",
    "EXPERIMENT_START",
    "EXPERIMENT_RESULT",
    "USER_QUESTION",
    "PHASE_START",
    "PHASE_COMPLETE",
    # Workspace file generation events (Phase A-D pipeline)
    "WORKSPACE_GENERATION_START",
    "WORKSPACE_GENERATION_DONE",
    "FILE_GENERATION_START",
    "FILE_GENERATED",
    "FILE_GENERATION_FAILED",
    "FILE_SYNTAX_ERROR",
    "FILE_IMPORT_ERROR",
    "FILE_FIXED",
    "GAP_ANALYSIS_COMPLETE",
    "GAP_ANALYSIS_SKIPPED",
    "GAP_FILE_START",
    "SMOKE_TEST_START",
    "SMOKE_TEST_DONE",
    "SMOKE_TEST_SKIPPED",
    # V4 interaction events
    "PLAN_AWAITING_APPROVAL",
    "USER_GUIDANCE_NEEDED",
    "USER_GUIDANCE_RECEIVED",
    "SECTION_DRAFT_DONE",
    # Preflight clarification events
    "PREFLIGHT_QUESTION",
    "PREFLIGHT_ANSWERED",
    # Mixed-case events used by Phase 2, 3, and orchestration
    "token_budget_snapshot",
    "token_budget_warning",
    "exec_stdout",
    "failure_escalation",
    "extension_proposals",
)

# Fast O(1) lookup set including uppercase aliases for all entries
_EVENT_TYPE_SET: frozenset[str] = frozenset(EVENT_TYPES)
_EVENT_TYPE_UPPER_MAP: dict[str, str] = {e.upper(): e for e in EVENT_TYPES}

TERMINAL_SESSION_STATUSES = ("completed", "failed")


def normalize_event_type(raw_event_type: Any) -> str:
    """Normalize event types to the canonical UI-safe taxonomy.

    Checks exact match first (supports mixed-case types like 'exec_stdout'),
    then falls back to a case-insensitive lookup.
    """
    if raw_event_type is None:
        return "AGENT_MESSAGE"
    s = str(raw_event_type).strip()
    if s in _EVENT_TYPE_SET:
        return s
    upper = s.upper()
    canonical = _EVENT_TYPE_UPPER_MAP.get(upper)
    if canonical is not None:
        return canonical
    return "AGENT_MESSAGE"


def normalize_session_status(raw_status: Any) -> str:
    """Normalize session status strings to a stable lowercase form."""
    if raw_status is None:
        return "queued"
    normalized = str(raw_status).strip().lower()
    return normalized or "queued"


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RunSession:
    """Canonical session metadata persisted by SessionStore."""

    run_id: str
    session_id: str
    research_topic: str
    research_goal: str | None = None
    research_domain: str | None = None
    status: str = "queued"
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str | None = None
    output_path: str | None = None
    error: str | None = None
    result_summary: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Return True when the session has reached a terminal state."""
        return self.status in TERMINAL_SESSION_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session as a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunSession":
        """Hydrate a session from persisted JSON."""
        normalized = dict(payload)
        normalized["status"] = normalize_session_status(normalized.get("status"))
        metadata = normalized.get("metadata")
        if not isinstance(metadata, dict):
            normalized["metadata"] = {}
        return cls(**normalized)


@dataclass(slots=True)
class RunEvent:
    """Canonical event payload persisted by EventStore."""

    run_id: str
    session_id: str
    event_type: str
    timestamp: str = field(default_factory=utc_now_iso)
    agent_name: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal_event(self) -> bool:
        """Return True when the event marks the end of the run."""
        return self.event_type == "SYSTEM_END"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event as a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunEvent":
        """Hydrate an event from persisted JSON."""
        normalized = dict(payload)
        normalized["event_type"] = normalize_event_type(normalized.get("event_type"))
        metadata = normalized.get("metadata")
        if not isinstance(metadata, dict):
            normalized["metadata"] = {}
        return cls(**normalized)


@dataclass(slots=True)
class ArtifactRecord:
    """Artifact metadata tracked per run."""

    path: str
    label: str
    kind: str = "file"
    content_type: str = "text/plain"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the artifact record as a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRecord":
        """Hydrate an artifact record from persisted JSON."""
        return cls(**payload)
