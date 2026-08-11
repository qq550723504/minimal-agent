from __future__ import annotations

from collections import Counter
from typing import Any

from plugins.park_security.server.mock_repository import MockSecurityRepository
from plugins.park_security.server.models import (
    AuditRecord,
    CreateWorkOrder,
    EventAction,
    EventListQuery,
    SecurityEvent,
    wrap_response,
)


class SecurityService:
    """Query the deterministic security data and manage its human-review workflow."""

    _CONFIRMED_AT = "2026-08-11T01:15:00Z"
    _CLOSED_AT = "2026-08-11T01:30:00Z"
    _RISK_SCORES = {"low": 1, "medium": 2, "high": 3, "critical": 4}

    def __init__(self, repository: MockSecurityRepository) -> None:
        self.repository = repository

    async def get_event_summary(self, park_id: str) -> dict[str, Any]:
        events = self.repository.list_events(park_id)
        raw_alarm_count = sum(len(event.alarm_ids) for event in events)
        merged_event_count = len(events)
        risk_counts = dict(Counter(event.risk_level for event in events))
        status_counts = dict(Counter(event.status for event in events))
        average_risk_score = (
            sum(self._RISK_SCORES[event.risk_level] for event in events) / merged_event_count
            if merged_event_count
            else 0.0
        )
        return wrap_response({
            "park_id": park_id,
            "total_events": merged_event_count,
            "risk_counts": risk_counts,
            "status_counts": status_counts,
            "raw_alarm_count": raw_alarm_count,
            "merged_event_count": merged_event_count,
            "duplicate_alarm_count": raw_alarm_count - merged_event_count,
            "effective_alarm_rate": merged_event_count / raw_alarm_count if raw_alarm_count else 0.0,
            "average_risk_score": average_risk_score,
        })

    async def list_events(self, query: EventListQuery) -> dict[str, Any]:
        events = sorted(
            (event for event in self.repository.list_events(query.park_id) if self._matches(event, query)),
            key=lambda event: event.first_occurred_at,
        )
        return wrap_response([self._event_card(event) for event in events])

    async def get_event_detail(self, event_id: str) -> dict[str, Any]:
        return wrap_response(self._event_detail(self._require_event(event_id)))

    async def get_shift_context(
        self, park_id: str, area_id: str | None = None
    ) -> dict[str, Any]:
        return wrap_response(self.repository.list_shift_context(park_id, area_id))

    async def confirm_event(self, action: EventAction) -> dict[str, Any]:
        event = self._require_event(action.event_id)
        if event.status != "open":
            raise ValueError("event_not_open")
        event.status = "confirmed"
        event.confirmed_at = self._CONFIRMED_AT
        event.audit_records.append(self._audit("confirmed", action, self._CONFIRMED_AT))
        return wrap_response(self._event_detail(self.repository.save_event(event)))

    async def create_work_order(self, action: CreateWorkOrder) -> dict[str, Any]:
        event = self._require_event(action.event_id)
        if event.status != "confirmed":
            raise ValueError("event_not_confirmed")
        work_order = self.repository.create_work_order(
            action.event_id, action.assignee, action.operator_id, action.note
        )
        event.status = "work_order_created"
        event.work_order_id = work_order.work_order_id
        event.work_orders.append(work_order)
        event.audit_records.append(
            self._audit("work_order_created", action, work_order.created_at)
        )
        return wrap_response(self._event_detail(self.repository.save_event(event)))

    async def close_event(self, action: EventAction) -> dict[str, Any]:
        event = self._require_event(action.event_id)
        if event.status not in {"confirmed", "work_order_created"}:
            raise ValueError("event_not_closable")
        event.status = "closed"
        event.closed_at = self._CLOSED_AT
        event.audit_records.append(self._audit("closed", action, self._CLOSED_AT))
        return wrap_response(self._event_detail(self.repository.save_event(event)))

    def _require_event(self, event_id: str) -> SecurityEvent:
        event = self.repository.get_event(event_id)
        if event is None:
            raise ValueError("event_not_found")
        return event

    @staticmethod
    def _matches(event: SecurityEvent, query: EventListQuery) -> bool:
        return (
            (query.start_time is None or event.first_occurred_at >= query.start_time)
            and (query.end_time is None or event.last_occurred_at <= query.end_time)
            and (query.risk_level is None or event.risk_level == query.risk_level)
            and (query.status is None or event.status == query.status)
        )

    @staticmethod
    def _event_card(event: SecurityEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "park_id": event.park_id,
            "building_id": event.building_id,
            "area_id": event.area_id,
            "scenario": event.scenario,
            "risk_level": event.risk_level,
            "status": event.status,
            "first_occurred_at": event.first_occurred_at,
            "last_occurred_at": event.last_occurred_at,
            "impact_scope": event.impact_scope,
            "recommended_plan": event.recommended_plan,
            "work_order_id": event.work_order_id,
        }

    def _event_detail(self, event: SecurityEvent) -> dict[str, Any]:
        detail = event.model_dump(mode="json")
        if event.status == "closed":
            detail["review_report"] = self._review_report(event)
        return detail

    @staticmethod
    def _audit(action_name: str, action: EventAction, occurred_at: str) -> AuditRecord:
        return AuditRecord(
            audit_id=f"audit-{action.event_id}-{action_name}",
            event_id=action.event_id,
            operator_id=action.operator_id,
            action=action_name,
            occurred_at=occurred_at,
            note=action.note,
        )

    @staticmethod
    def _review_report(event: SecurityEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "final_risk_level": event.risk_level,
            "handling_process": [record.action for record in event.audit_records],
            "evidence_completeness": event.evidence_completeness,
            "closed_at": event.closed_at,
        }
