"""API request and response models for the V4 pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchRequest(BaseModel):
    """Research run request for the V4 pipeline."""

    model_config = ConfigDict(extra="allow")

    topic: str = Field(..., min_length=1)
    goal: str | None = None
    domain: str | None = None
    # V4: optional user-specified output directory
    workspace_path: str | None = None
    data_path: str | None = None
    data_description: str | None = None
    frameworks: list[str] | None = None
    constraints: list[str] | None = None

    def to_coordinator_input(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def to_research_input(self) -> dict[str, Any]:
        return self.to_coordinator_input()


class ResearchCreateResponse(BaseModel):
    """Response returned after a research run is accepted."""

    run_id: str
    session_id: str
    status: str
