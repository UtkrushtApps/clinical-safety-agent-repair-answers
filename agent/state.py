from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class IncidentRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=200)
    study_id: str = Field(min_length=1, max_length=100)
    site_id: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=100)
    received_at: datetime
    channel: str = Field(min_length=1, max_length=100)
    narrative: str = Field(min_length=1, max_length=20000)

    @field_validator("report_id", "study_id", "site_id", "subject_id", "channel")
    @classmethod
    def strip_identifiers(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identifier must not be blank")
        return value


class SpecialistResult(BaseModel):
    agent_name: str
    conclusion: str
    tool_activity: list[dict[str, Any]] = Field(default_factory=list)
    model_calls: int = 0
    bounded_stop: bool = False


class RunState(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    incident: IncidentRequest
    case_id: str | None = None
    intake_created: bool = False
    selected_agents: list[str] = Field(default_factory=list)
    specialist_results: list[SpecialistResult] = Field(default_factory=list)
    final_result: dict[str, Any] | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
