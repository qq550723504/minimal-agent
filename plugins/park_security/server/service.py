from __future__ import annotations

from collections import Counter
import os
import secrets
from typing import Any

from plugins.park_security.server.mock_repository import MockSecurityRepository
from plugins.park_security.server.models import (
    AuditRecord,
    CloseEventAction,
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

    def __init__(
        self,
        repository: MockSecurityRepository,
        approval_token: str | None = None,
    ) -> None:
        self.repository = repository
        configured_token = (
            approval_token
            if approval_token is not None
            else os.getenv("PARK_SECURITY_APPROVAL_TOKEN", "")
        )
        self._approval_token = configured_token.strip() or None

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
        self._require_approval(action)
        event = self._require_event(action.event_id)
        if event.status != "open":
            raise ValueError("event_not_open")
        event.status = "confirmed"
        event.confirmed_at = self._CONFIRMED_AT
        event.audit_records.append(self._audit("confirmed", action, self._CONFIRMED_AT))
        return wrap_response(self._event_detail(self.repository.save_event(event)))

    async def create_work_order(self, action: CreateWorkOrder) -> dict[str, Any]:
        self._require_approval(action)
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

    async def close_event(self, action: CloseEventAction) -> dict[str, Any]:
        self._require_approval(action)
        event = self._require_event(action.event_id)
        if event.status not in {"confirmed", "work_order_created"}:
            raise ValueError("event_not_closable")
        if event.work_order_id is not None:
            closed_work_order = self.repository.close_work_order(
                event.work_order_id, self._CLOSED_AT
            )
            event.work_orders = [
                closed_work_order
                if item.work_order_id == closed_work_order.work_order_id
                else item
                for item in event.work_orders
            ]
        event.status = "closed"
        event.closed_at = self._CLOSED_AT
        event.audit_records.append(self._audit("closed", action, self._CLOSED_AT))
        return wrap_response(self._event_detail(self.repository.save_event(event)))

    def _require_approval(self, action: EventAction) -> None:
        if self._approval_token is None:
            raise ValueError("approval_not_configured")
        if not secrets.compare_digest(action.approval_token, self._approval_token):
            raise ValueError("approval_denied")

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
        closed_record = next(
            record for record in reversed(event.audit_records) if record.action == "closed"
        )
        return {
            "event_id": event.event_id,
            "final_risk_level": event.risk_level,
            "disposition": closed_record.note,
            "handling_process": [record.action for record in event.audit_records],
            "timeline": [item.model_dump(mode="json") for item in event.timeline],
            "evidence_completeness": event.evidence_completeness,
            "closed_at": event.closed_at,
        }
