from __future__ import annotations

from typing import Any

from plugins.park_security.server.correlation import CorrelatedAlarmGroup, EventCorrelator
from plugins.park_security.server.models import (
    EvidenceItem,
    SecurityAlarm,
    SecurityEvent,
    WorkOrder,
    parse_timestamp,
)
from plugins.park_security.server.mock_fixtures import (
    build_event as fixture_build_event,
    build_mock_alarms,
    build_timeline as fixture_build_timeline,
)
from plugins.park_security.server.risk import RiskAssessment, RiskAssessor


class MockSecurityRepository:
    """Deterministic in-memory security data for the park-security mock server."""

    def __init__(
        self,
        correlator: EventCorrelator | None = None,
        risk_assessor: RiskAssessor | None = None,
    ) -> None:
        self._alarms = self._build_alarms()
        self._correlator = correlator or EventCorrelator()
        self._risk_assessor = risk_assessor or RiskAssessor()
        self._events = self._build_events()
        self._work_orders: dict[str, WorkOrder] = {}

    def list_events(self, park_id: str) -> list[SecurityEvent]:
        return [
            event.model_copy(deep=True)
            for event in self._events.values()
            if event.park_id == park_id
        ]

    def get_event(self, event_id: str) -> SecurityEvent | None:
        event = self._events.get(event_id)
        return event.model_copy(deep=True) if event is not None else None

    def save_event(self, event: SecurityEvent) -> SecurityEvent:
        self._events[event.event_id] = event.model_copy(deep=True)
        return self._events[event.event_id].model_copy(deep=True)

    def create_work_order(
        self, event_id: str, assignee: str, operator_id: str, note: str | None
    ) -> WorkOrder:
        work_order_id = f"wo-{event_id}"
        if work_order_id in self._work_orders:
            raise ValueError("work_order_exists")

        event = self._events.get(event_id)
        if event is None:
            raise ValueError("event_not_found")

        work_order = WorkOrder(
            work_order_id=work_order_id,
            event_id=event_id,
            assignee=assignee,
            operator_id=operator_id,
            created_at="2026-08-11T01:20:00Z",
            note=note,
        )
        self._work_orders[work_order_id] = work_order.model_copy(deep=True)
        stored_event = event.model_copy(deep=True)
        stored_event.work_order_id = work_order_id
        stored_event.work_orders.append(work_order.model_copy(deep=True))
        stored_event.status = "work_order_created"
        self._events[event_id] = stored_event
        return work_order.model_copy(deep=True)

    def close_work_order(self, work_order_id: str, closed_at: str) -> WorkOrder:
        work_order = self._work_orders.get(work_order_id)
        if work_order is None:
            raise ValueError("work_order_not_found")

        closed = work_order.model_copy(
            update={"status": "closed", "closed_at": closed_at}, deep=True
        )
        self._work_orders[work_order_id] = closed
        event = self._events[closed.event_id].model_copy(deep=True)
        event.work_orders = [
            closed.model_copy(deep=True)
            if item.work_order_id == work_order_id
            else item
            for item in event.work_orders
        ]
        self._events[event.event_id] = event
        return closed.model_copy(deep=True)

    def list_shift_context(
        self,
        park_id: str,
        area_id: str | None,
        query_time: str | None = None,
    ) -> dict[str, Any]:
        if park_id != "park-1":
            raise ValueError("park_not_found")
        known_areas = {"area-lab-01", "area-gate-02", "area-plant-01"}
        if area_id is not None and area_id not in known_areas:
            raise ValueError("area_not_found")
        focus_area = area_id or "area-lab-01"
        shift_start = "2026-08-10T16:00:00Z"
        shift_end = "2026-08-11T08:00:00Z"
        effective_query_time = query_time or "2026-08-11T01:00:00Z"
        on_duty = (
            parse_timestamp(shift_start)
            <= parse_timestamp(effective_query_time)
            <= parse_timestamp(shift_end)
        )
        return {
            "park_id": park_id,
            "focus_area": focus_area,
            "query_time": effective_query_time,
            "on_duty": on_duty,
            "key_areas": ["area-lab-01", "area-gate-02", "area-plant-01"],
            "on_duty_guard": {
                "guard_id": "guard-01",
                "name": "Li Wei",
                "shift": "night",
                "shift_start": shift_start,
                "shift_end": shift_end,
            } if on_duty else None,
            "responsible_areas": ["area-lab-01", "area-gate-02", "area-plant-01"],
            "escalation_rules": {
                "level_1": {
                    "condition": "high risk or access anomaly",
                    "notify": ["guard-01", "team-night"] if on_duty else ["team-night"],
                    "response_within_minutes": 5,
                },
                "level_2": {
                    "condition": "critical fire or life-safety alarm",
                    "notify": ["team-fire", "park-manager", "emergency-services"],
                    "response_within_minutes": 1,
                },
            },
        }

    @staticmethod
    def _build_alarms() -> dict[str, SecurityAlarm]:
        return build_mock_alarms()

    def _build_events(self) -> dict[str, SecurityEvent]:
        events = [
            self._build_event(group, self._risk_assessor.assess(group))
            for group in self._correlator.correlate(self._alarms.values())
        ]
        return {event.event_id: event for event in events}

    @staticmethod
    def _build_event(
        group: CorrelatedAlarmGroup, assessment: RiskAssessment
    ) -> SecurityEvent:
        return fixture_build_event(group, assessment)

    @staticmethod
    def _build_timeline(
        scenario: str, alarms: dict[str, SecurityAlarm]
    ) -> tuple[list[EvidenceItem], str]:
        return fixture_build_timeline(scenario, alarms)
