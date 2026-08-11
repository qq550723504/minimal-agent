from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from plugins.park_security.server.models import (
    AuditRecord,
    EvidenceItem,
    RiskLevel,
    SecurityAlarm,
    SecurityEvent,
    WorkOrder,
    parse_timestamp,
)
from plugins.park_security.server.correlation import CorrelatedAlarmGroup, EventCorrelator


@dataclass(frozen=True)
class RiskAssessment:
    risk_level: RiskLevel
    impact_scope: tuple[str, ...]
    recommended_plan: str
    responsible_party: str
    evidence_completeness: float


class RiskAssessor:
    """Apply explicit deterministic risk and response rules to a correlated group."""

    def assess(self, group: CorrelatedAlarmGroup) -> RiskAssessment:
        first = group.alarms[0]
        base_scope = tuple(value for value in (first.building_id, first.area_id) if value)
        if group.scenario == "night_abnormal_access":
            return RiskAssessment(
                risk_level="high",
                impact_scope=(*base_scope, "night-research-zone"),
                recommended_plan="night_access_verification",
                responsible_party="team-night",
                evidence_completeness=0.92,
            )
        if group.scenario == "access_failure_and_loitering":
            attempts = max(
                (
                    int(alarm.payload.get("attempt_count", 1))
                    for alarm in group.alarms
                    if alarm.alarm_type == "repeated_access_failure"
                ),
                default=1,
            )
            return RiskAssessment(
                risk_level="high" if attempts > 1 else "medium",
                impact_scope=(*base_scope, "visitor-entry-route"),
                recommended_plan="verify_visitor_appointment_and_dispatch_patrol",
                responsible_party="team-access",
                evidence_completeness=0.88,
            )
        if group.scenario == "fire_alarm_and_equipment_fault":
            return RiskAssessment(
                risk_level="critical",
                impact_scope=(*base_scope, "mechanical-room", "evacuation-zone-a"),
                recommended_plan="fire_emergency_response",
                responsible_party="team-fire",
                evidence_completeness=0.97,
            )
        raise ValueError("unsupported_security_scenario")


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
                payload={"subject_id": "person-001"},
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
                payload={"subject_id": "person-001"},
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
                payload={"attempt_count": 3, "subject_id": "visitor-002"},
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
                payload={"subject_id": "visitor-002"},
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
                payload={"subject_id": "visitor-002"},
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
                payload={"device_group_id": "plant-01"},
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
                payload={"device_group_id": "plant-01"},
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
                payload={"device_group_id": "plant-01"},
            ),
        }

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
        event_ids = {
            "night_abnormal_access": "event-night-001",
            "access_failure_and_loitering": "event-access-002",
            "fire_alarm_and_equipment_fault": "event-fire-003",
        }
        event_id = event_ids[group.scenario]
        alarms = {alarm.alarm_type: alarm for alarm in group.alarms}
        first = group.alarms[0]
        timeline, audit_at = MockSecurityRepository._build_timeline(group.scenario, alarms)
        return SecurityEvent(
            event_id=event_id,
            park_id=first.park_id,
            building_id=first.building_id,
            area_id=first.area_id,
            scenario=group.scenario,
            risk_level=assessment.risk_level,
            first_occurred_at=min(
                group.alarms, key=lambda alarm: parse_timestamp(alarm.occurred_at)
            ).occurred_at,
            last_occurred_at=max(
                group.alarms, key=lambda alarm: parse_timestamp(alarm.occurred_at)
            ).occurred_at,
            alarm_ids=[alarm.alarm_id for alarm in group.alarms],
            impact_scope=list(assessment.impact_scope),
            recommended_plan=assessment.recommended_plan,
            responsible_party=assessment.responsible_party,
            evidence_completeness=assessment.evidence_completeness,
            timeline=timeline,
            audit_records=[
                _audit(
                    f"audit-{event_id.removeprefix('event-')}",
                    event_id,
                    "guard-01",
                    "event_created",
                    audit_at,
                )
            ],
        )

    @staticmethod
    def _build_timeline(
        scenario: str, alarms: dict[str, SecurityAlarm]
    ) -> tuple[list[EvidenceItem], str]:
        if scenario == "night_abnormal_access":
            access = alarms["after_hours_access"]
            video = alarms["person_detected"]
            return ([
                _evidence(
                    "evidence-night-access",
                    "access_control",
                    access.occurred_at,
                    "After-hours access attempt denied.",
                    f"access://{access.device_id}/log/001",
                ),
                _evidence(
                    "evidence-night-video",
                    "video",
                    video.occurred_at,
                    "Person detected near laboratory door.",
                    "s3://park-security/screenshots/night-001.jpg",
                ),
                _evidence(
                    "evidence-night-shift",
                    "shift",
                    "2026-08-11T00:15:00Z",
                    "Guard-01 is assigned to the north patrol route.",
                    "shift://2026-08-11/guard-01",
                ),
                _evidence(
                    "evidence-night-appointment",
                    "appointment",
                    "2026-08-11T00:15:00Z",
                    "No active visitor appointment matched the credential.",
                    "appointment://lab-01/lookup/001",
                ),
            ], "2026-08-11T00:15:00Z")
        if scenario == "access_failure_and_loitering":
            access = alarms["repeated_access_failure"]
            patrol = alarms["loitering_report"]
            video = alarms["loitering_detected"]
            return ([
                _evidence(
                    "evidence-access-reader",
                    "access_control",
                    access.occurred_at,
                    "Three failed credential attempts recorded.",
                    f"access://{access.device_id}/log/002",
                ),
                _evidence(
                    "evidence-access-video",
                    "video",
                    video.occurred_at,
                    "Person remained at gate after denial.",
                    "s3://park-security/screenshots/access-002.jpg",
                ),
                _evidence(
                    "evidence-access-patrol",
                    "patrol",
                    patrol.occurred_at,
                    "Patrol reported continued loitering at the gate.",
                    f"patrol://{patrol.device_id}/report/002",
                ),
                _evidence(
                    "evidence-access-appointment",
                    "appointment",
                    "2026-08-11T00:50:00Z",
                    "No active visitor appointment matched the credential.",
                    "appointment://gate-02/lookup/002",
                ),
            ], "2026-08-11T00:50:00Z")
        if scenario == "fire_alarm_and_equipment_fault":
            smoke = alarms["smoke_detected"]
            temperature = alarms["temperature_rise"]
            device = alarms["ventilation_device_fault"]
            return ([
                _evidence(
                    "evidence-fire-smoke",
                    "fire",
                    smoke.occurred_at,
                    "Smoke detector alarmed in plant room.",
                    f"fire://{smoke.device_id}/event/003",
                ),
                _evidence(
                    "evidence-fire-temperature",
                    "fire",
                    temperature.occurred_at,
                    "Temperature rose above the fire threshold.",
                    f"fire://{temperature.device_id}/event/003",
                ),
                _evidence(
                    "evidence-fire-device",
                    "device",
                    device.occurred_at,
                    "Ventilation fan reported a fault state.",
                    f"device://{device.device_id}/status/003",
                ),
            ], "2026-08-11T01:05:00Z")
        raise ValueError("unsupported_security_scenario")
