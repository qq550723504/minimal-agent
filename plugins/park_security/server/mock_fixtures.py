from __future__ import annotations

from plugins.park_security.server.correlation import CorrelatedAlarmGroup
from plugins.park_security.server.models import (
    AuditRecord,
    EvidenceItem,
    SecurityAlarm,
    SecurityEvent,
    parse_timestamp,
)
from plugins.park_security.server.risk import RiskAssessment


def _evidence(
    evidence_id: str, source: str, occurred_at: str, summary: str, reference: str
) -> EvidenceItem:
    """构造一条统一格式的证据时间线记录。"""
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
    """构造事件创建或处置过程中的审计记录。"""
    return AuditRecord(
        audit_id=audit_id,
        event_id=event_id,
        operator_id=operator_id,
        action=action,
        occurred_at=occurred_at,
    )


def build_mock_alarms() -> dict[str, SecurityAlarm]:
    """返回确定性的八条视频、门禁、消防和巡更 Mock 告警。"""
    return {
        "alarm-access-001": SecurityAlarm(
            alarm_id="alarm-access-001", source="access_control", park_id="park-1",
            building_id="building-a", area_id="area-lab-01", device_id="door-lab-01",
            occurred_at="2026-08-11T00:12:00Z", alarm_type="after_hours_access",
            severity="high", payload={"subject_id": "person-001"},
        ),
        "alarm-video-001": SecurityAlarm(
            alarm_id="alarm-video-001", source="video", park_id="park-1",
            building_id="building-a", area_id="area-lab-01", device_id="camera-lab-01",
            occurred_at="2026-08-11T00:14:00Z", alarm_type="person_detected",
            severity="high", payload={"subject_id": "person-001"},
        ),
        "alarm-access-002": SecurityAlarm(
            alarm_id="alarm-access-002", source="access_control", park_id="park-1",
            building_id="building-a", area_id="area-gate-02", device_id="gate-reader-02",
            occurred_at="2026-08-11T00:42:00Z", alarm_type="repeated_access_failure",
            severity="medium", payload={"attempt_count": 3, "subject_id": "visitor-002"},
        ),
        "alarm-patrol-001": SecurityAlarm(
            alarm_id="alarm-patrol-001", source="patrol", park_id="park-1",
            building_id="building-a", area_id="area-gate-02", device_id="patrol-point-02",
            occurred_at="2026-08-11T00:47:00Z", alarm_type="loitering_report",
            severity="high", payload={"subject_id": "visitor-002"},
        ),
        "alarm-video-002": SecurityAlarm(
            alarm_id="alarm-video-002", source="video", park_id="park-1",
            building_id="building-a", area_id="area-gate-02", device_id="camera-gate-02",
            occurred_at="2026-08-11T00:49:00Z", alarm_type="loitering_detected",
            severity="high", payload={"subject_id": "visitor-002"},
        ),
        "alarm-fire-001": SecurityAlarm(
            alarm_id="alarm-fire-001", source="fire", park_id="park-1",
            building_id="building-a", area_id="area-plant-01", device_id="smoke-plant-01",
            occurred_at="2026-08-11T01:02:00Z", alarm_type="smoke_detected",
            severity="critical", payload={"device_group_id": "plant-01"},
        ),
        "alarm-fire-002": SecurityAlarm(
            alarm_id="alarm-fire-002", source="fire", park_id="park-1",
            building_id="building-a", area_id="area-plant-01", device_id="temp-plant-01",
            occurred_at="2026-08-11T01:03:00Z", alarm_type="temperature_rise",
            severity="critical", payload={"device_group_id": "plant-01"},
        ),
        "alarm-fire-003": SecurityAlarm(
            alarm_id="alarm-fire-003", source="fire", park_id="park-1",
            building_id="building-a", area_id="area-plant-01", device_id="fan-plant-01",
            occurred_at="2026-08-11T01:04:00Z", alarm_type="ventilation_device_fault",
            severity="high", payload={"device_group_id": "plant-01"},
        ),
    }


def build_event(
    group: CorrelatedAlarmGroup, assessment: RiskAssessment
) -> SecurityEvent:
    """将归并结果和风险评估组装为对外展示的事件卡片。"""
    event_ids = {
        "night_abnormal_access": "event-night-001",
        "access_failure_and_loitering": "event-access-002",
        "fire_alarm_and_equipment_fault": "event-fire-003",
    }
    event_id = event_ids[group.scenario]
    alarms = {alarm.alarm_type: alarm for alarm in group.alarms}
    timeline, audit_at = build_timeline(group.scenario, alarms)
    first = group.alarms[0]
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


def build_timeline(
    scenario: str, alarms: dict[str, SecurityAlarm]
) -> tuple[list[EvidenceItem], str]:
    """根据场景生成证据时间线及对应的审计时间。"""
    if scenario == "night_abnormal_access":
        access = alarms["after_hours_access"]
        video = alarms["person_detected"]
        return ([
            _evidence("evidence-night-access", "access_control", access.occurred_at,
                      "After-hours access attempt denied.", f"access://{access.device_id}/log/001"),
            _evidence("evidence-night-video", "video", video.occurred_at,
                      "Person detected near laboratory door.", "s3://park-security/screenshots/night-001.jpg"),
            _evidence("evidence-night-shift", "shift", "2026-08-11T00:15:00Z",
                      "Guard-01 is assigned to the north patrol route.", "shift://2026-08-11/guard-01"),
            _evidence("evidence-night-appointment", "appointment", "2026-08-11T00:15:00Z",
                      "No active visitor appointment matched the credential.", "appointment://lab-01/lookup/001"),
        ], "2026-08-11T00:15:00Z")
    if scenario == "access_failure_and_loitering":
        access = alarms["repeated_access_failure"]
        patrol = alarms["loitering_report"]
        video = alarms["loitering_detected"]
        return ([
            _evidence("evidence-access-reader", "access_control", access.occurred_at,
                      "Three failed credential attempts recorded.", f"access://{access.device_id}/log/002"),
            _evidence("evidence-access-video", "video", video.occurred_at,
                      "Person remained at gate after denial.", "s3://park-security/screenshots/access-002.jpg"),
            _evidence("evidence-access-patrol", "patrol", patrol.occurred_at,
                      "Patrol reported continued loitering at the gate.", f"patrol://{patrol.device_id}/report/002"),
            _evidence("evidence-access-appointment", "appointment", "2026-08-11T00:50:00Z",
                      "No active visitor appointment matched the credential.", "appointment://gate-02/lookup/002"),
        ], "2026-08-11T00:50:00Z")
    if scenario == "fire_alarm_and_equipment_fault":
        smoke = alarms["smoke_detected"]
        temperature = alarms["temperature_rise"]
        device = alarms["ventilation_device_fault"]
        return ([
            _evidence("evidence-fire-smoke", "fire", smoke.occurred_at,
                      "Smoke detector alarmed in plant room.", f"fire://{smoke.device_id}/event/003"),
            _evidence("evidence-fire-temperature", "fire", temperature.occurred_at,
                      "Temperature rose above the fire threshold.", f"fire://{temperature.device_id}/event/003"),
            _evidence("evidence-fire-device", "device", device.occurred_at,
                      "Ventilation fan reported a fault state.", f"device://{device.device_id}/status/003"),
        ], "2026-08-11T01:05:00Z")
    raise ValueError("unsupported_security_scenario")
