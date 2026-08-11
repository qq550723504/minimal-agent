from __future__ import annotations

from dataclasses import dataclass

from plugins.park_security.server.correlation import CorrelatedAlarmGroup
from plugins.park_security.server.models import RiskLevel


@dataclass(frozen=True)
class RiskAssessment:
    risk_level: RiskLevel
    impact_scope: tuple[str, ...]
    recommended_plan: str
    responsible_party: str
    evidence_completeness: float


class RiskAssessor:
    """根据显式规则为归并事件计算风险和处置建议。"""

    def assess(self, group: CorrelatedAlarmGroup) -> RiskAssessment:
        """根据场景和告警载荷计算风险等级、影响范围及推荐预案。"""
        first = group.alarms[0]
        building_scope = tuple(
            value for value in dict.fromkeys(alarm.building_id for alarm in group.alarms) if value
        )
        area_scope = tuple(
            value for value in dict.fromkeys(alarm.area_id for alarm in group.alarms) if value
        )
        base_scope = (*building_scope, *area_scope)
        if group.scenario == "night_abnormal_access":
            return RiskAssessment(
                risk_level="high",
                impact_scope=(*base_scope, "night-research-zone"),
                recommended_plan="night_access_verification",
                responsible_party="team-night",
                evidence_completeness=0.92,
            )
        if group.scenario == "access_failure_and_loitering":
            attempts = sum(
                int(alarm.payload.get("attempt_count", 1))
                for alarm in group.alarms
                if alarm.alarm_type == "repeated_access_failure"
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
