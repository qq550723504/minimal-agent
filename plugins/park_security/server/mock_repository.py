from __future__ import annotations

from typing import Any

from plugins.park_security.server.models import (
    AuditRecord,
    EvidenceItem,
    SecurityAlarm,
    SecurityEvent,
    WorkOrder,
)


def _evidence(
    evidence_id: str, source: str, occurred_at: str, summary: str, reference: str
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source=source,
        occurred_at=occurred_at,
        summary=summary,
        reference=reference,
    )


def _audit(
    audit_id: str, event_id: str, operator_id: str, action: str, occurred_at: str
) -> AuditRecord:
    return AuditRecord(
        audit_id=audit_id,
        event_id=event_id,
        operator_id=operator_id,
        action=action,
        occurred_at=occurred_at,
    )


class MockSecurityRepository:
    """Deterministic in-memory security data for the park-security mock server."""

    def __init__(self) -> None:
        self._alarms = self._build_alarms()
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

    def list_shift_context(self, park_id: str, area_id: str | None) -> dict[str, Any]:
        focus_area = area_id or "area-lab-01"
        return {
            "park_id": park_id,
            "focus_area": focus_area,
            "key_areas": ["area-lab-01", "area-gate-02", "area-plant-01"],
            "on_duty_guard": {
                "guard_id": "guard-01",
                "name": "Li Wei",
                "shift": "night",
                "shift_start": "2026-08-10T16:00:00Z",
                "shift_end": "2026-08-11T08:00:00Z",
            },
            "responsible_areas": ["area-lab-01", "area-gate-02", "area-plant-01"],
            "escalation_rules": {
                "level_1": {
                    "condition": "high risk or access anomaly",
                    "notify": ["guard-01", "team-night"],
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
        return {
            "alarm-access-001": SecurityAlarm(
                alarm_id="alarm-access-001",
                source="access_control",
                park_id="park-1",
                building_id="building-a",
                area_id="area-lab-01",
                device_id="door-lab-01",
                occurred_at="2026-08-11T00:12:00Z",
                alarm_type="after_hours_access",
                severity="high",
            ),
            "alarm-video-001": SecurityAlarm(
                alarm_id="alarm-video-001",
                source="video",
                park_id="park-1",
                building_id="building-a",
                area_id="area-lab-01",
                device_id="camera-lab-01",
                occurred_at="2026-08-11T00:14:00Z",
                alarm_type="person_detected",
                severity="high",
            ),
            "alarm-access-002": SecurityAlarm(
                alarm_id="alarm-access-002",
                source="access_control",
                park_id="park-1",
                building_id="building-a",
                area_id="area-gate-02",
                device_id="gate-reader-02",
                occurred_at="2026-08-11T00:42:00Z",
                alarm_type="repeated_access_failure",
                severity="medium",
            ),
            "alarm-patrol-001": SecurityAlarm(
                alarm_id="alarm-patrol-001",
                source="patrol",
                park_id="park-1",
                building_id="building-a",
                area_id="area-gate-02",
                device_id="patrol-point-02",
                occurred_at="2026-08-11T00:47:00Z",
                alarm_type="loitering_report",
                severity="high",
            ),
            "alarm-video-002": SecurityAlarm(
                alarm_id="alarm-video-002",
                source="video",
                park_id="park-1",
                building_id="building-a",
                area_id="area-gate-02",
                device_id="camera-gate-02",
                occurred_at="2026-08-11T00:49:00Z",
                alarm_type="loitering_detected",
                severity="high",
            ),
            "alarm-fire-001": SecurityAlarm(
                alarm_id="alarm-fire-001",
                source="fire",
                park_id="park-1",
                building_id="building-a",
                area_id="area-plant-01",
                device_id="smoke-plant-01",
                occurred_at="2026-08-11T01:02:00Z",
                alarm_type="smoke_detected",
                severity="critical",
            ),
            "alarm-fire-002": SecurityAlarm(
                alarm_id="alarm-fire-002",
                source="fire",
                park_id="park-1",
                building_id="building-a",
                area_id="area-plant-01",
                device_id="temp-plant-01",
                occurred_at="2026-08-11T01:03:00Z",
                alarm_type="temperature_rise",
                severity="critical",
            ),
            "alarm-fire-003": SecurityAlarm(
                alarm_id="alarm-fire-003",
                source="fire",
                park_id="park-1",
                building_id="building-a",
                area_id="area-plant-01",
                device_id="fan-plant-01",
                occurred_at="2026-08-11T01:04:00Z",
                alarm_type="ventilation_device_fault",
                severity="high",
            ),
        }

    @staticmethod
    def _build_events() -> dict[str, SecurityEvent]:
        return {
            "event-night-001": SecurityEvent(
                event_id="event-night-001",
                park_id="park-1",
                building_id="building-a",
                area_id="area-lab-01",
                scenario="night_abnormal_access",
                risk_level="high",
                first_occurred_at="2026-08-11T00:12:00Z",
                last_occurred_at="2026-08-11T00:14:00Z",
                alarm_ids=["alarm-access-001", "alarm-video-001"],
                impact_scope=["building-a", "area-lab-01", "night-research-zone"],
                recommended_plan="night_access_verification",
                responsible_party="team-night",
                evidence_completeness=0.92,
                timeline=[
                    _evidence("evidence-night-access", "access_control", "2026-08-11T00:12:00Z", "After-hours access attempt denied.", "access://door-lab-01/log/001"),
                    _evidence("evidence-night-video", "video", "2026-08-11T00:14:00Z", "Person detected near laboratory door.", "s3://park-security/screenshots/night-001.jpg"),
                    _evidence("evidence-night-shift", "shift", "2026-08-11T00:15:00Z", "Guard-01 is assigned to the north patrol route.", "shift://2026-08-11/guard-01"),
                ],
                audit_records=[_audit("audit-night-001", "event-night-001", "guard-01", "event_created", "2026-08-11T00:15:00Z")],
            ),
            "event-access-002": SecurityEvent(
                event_id="event-access-002",
                park_id="park-1",
                building_id="building-a",
                area_id="area-gate-02",
                scenario="access_failure_and_loitering",
                risk_level="high",
                first_occurred_at="2026-08-11T00:42:00Z",
                last_occurred_at="2026-08-11T00:49:00Z",
                alarm_ids=["alarm-access-002", "alarm-patrol-001", "alarm-video-002"],
                impact_scope=["building-a", "area-gate-02", "visitor-entry-route"],
                recommended_plan="verify_visitor_appointment_and_dispatch_patrol",
                responsible_party="team-access",
                evidence_completeness=0.88,
                timeline=[
                    _evidence("evidence-access-reader", "access_control", "2026-08-11T00:42:00Z", "Three failed credential attempts recorded.", "access://gate-reader-02/log/002"),
                    _evidence("evidence-access-video", "video", "2026-08-11T00:49:00Z", "Person remained at gate after denial.", "s3://park-security/screenshots/access-002.jpg"),
                    _evidence("evidence-access-appointment", "appointment", "2026-08-11T00:50:00Z", "No active visitor appointment matched the credential.", "appointment://gate-02/lookup/002"),
                ],
                audit_records=[_audit("audit-access-002", "event-access-002", "guard-01", "event_created", "2026-08-11T00:50:00Z")],
            ),
            "event-fire-003": SecurityEvent(
                event_id="event-fire-003",
                park_id="park-1",
                building_id="building-a",
                area_id="area-plant-01",
                scenario="fire_alarm_and_equipment_fault",
                risk_level="critical",
                first_occurred_at="2026-08-11T01:02:00Z",
                last_occurred_at="2026-08-11T01:04:00Z",
                alarm_ids=["alarm-fire-001", "alarm-fire-002", "alarm-fire-003"],
                impact_scope=["building-a", "area-plant-01", "mechanical-room", "evacuation-zone-a"],
                recommended_plan="activate_fire_response_and_inspect_ventilation",
                responsible_party="team-fire",
                evidence_completeness=0.97,
                timeline=[
                    _evidence("evidence-fire-smoke", "fire", "2026-08-11T01:02:00Z", "Smoke detector alarmed in plant room.", "fire://smoke-plant-01/event/003"),
                    _evidence("evidence-fire-temperature", "fire", "2026-08-11T01:03:00Z", "Temperature rose above the fire threshold.", "fire://temp-plant-01/event/003"),
                    _evidence("evidence-fire-device", "device", "2026-08-11T01:04:00Z", "Ventilation fan reported a fault state.", "device://fan-plant-01/status/003"),
                ],
                audit_records=[_audit("audit-fire-003", "event-fire-003", "guard-01", "event_created", "2026-08-11T01:05:00Z")],
            ),
        }
