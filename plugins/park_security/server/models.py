from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator


EventStatus = Literal["open", "confirmed", "work_order_created", "closed"]
RiskLevel = Literal["low", "medium", "high", "critical"]
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def normalize_timestamp(value: str) -> str:
    """Normalize a timezone-aware ISO 8601 timestamp to UTC with a Z suffix."""
    if not isinstance(value, str):
        raise ValueError("valid ISO 8601 timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("valid ISO 8601 timestamp is required") from error
    if parsed.tzinfo is None:
        raise ValueError("valid ISO 8601 timestamp with timezone is required")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    """Parse a stored timestamp as an aware datetime for instant comparisons."""
    return datetime.fromisoformat(normalize_timestamp(value).replace("Z", "+00:00"))


class SecurityAlarm(BaseModel):
    alarm_id: str = Field(min_length=1)
    source: Literal["video", "access_control", "fire", "patrol"]
    park_id: str = Field(min_length=1)
    building_id: str | None = Field(default=None, min_length=1)
    area_id: str | None = Field(default=None, min_length=1)
    device_id: str | None = Field(default=None, min_length=1)
    occurred_at: str = "1970-01-01T00:00:00Z"
    alarm_type: str = "unknown"
    severity: RiskLevel = "low"
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    evidence_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    occurred_at: str = "1970-01-01T00:00:00Z"
    summary: str = ""
    reference: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditRecord(BaseModel):
    audit_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    occurred_at: str = "1970-01-01T00:00:00Z"
    note: str | None = None


class WorkOrder(BaseModel):
    work_order_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    status: str = "open"
    assignee: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    created_at: str = "1970-01-01T00:00:00Z"
    closed_at: str | None = None
    note: str | None = None


class SecurityEvent(BaseModel):
    event_id: str = Field(min_length=1)
    park_id: str = Field(min_length=1)
    building_id: str | None = Field(default=None, min_length=1)
    area_id: str | None = Field(default=None, min_length=1)
    scenario: str = "unknown"
    risk_level: RiskLevel = "low"
    status: EventStatus = "open"
    first_occurred_at: str = "1970-01-01T00:00:00Z"
    last_occurred_at: str = "1970-01-01T00:00:00Z"
    alarm_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    impact_scope: list[str] = Field(default_factory=list)
    recommended_plan: str = ""
    responsible_party: str | None = Field(default=None, min_length=1)
    evidence_completeness: float = 0.0
    timeline: list[EvidenceItem] = Field(default_factory=list)
    audit_records: list[AuditRecord] = Field(default_factory=list)
    work_order_id: str | None = Field(default=None, min_length=1)
    work_orders: list[WorkOrder] = Field(default_factory=list)
    confirmed_at: str | None = None
    closed_at: str | None = None


class EventListQuery(BaseModel):
    park_id: str = Field(min_length=1)
    start_time: str | None = None
    end_time: str | None = None
    risk_level: RiskLevel | None = None
    status: EventStatus | None = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def validate_query_timestamp(cls, value: str | None) -> str | None:
        return None if value is None else normalize_timestamp(value)


class EventAction(BaseModel):
    event_id: str = Field(min_length=1)
    operator_id: NonBlankText
    approval_token: NonBlankText = Field(repr=False)
    note: str | None = None


class CreateWorkOrder(EventAction):
    assignee: NonBlankText


class CloseEventAction(EventAction):
    note: NonBlankText


def wrap_response(payload: Any) -> dict[str, Any]:
    return {"success": True, "data": payload, "raw": payload}
