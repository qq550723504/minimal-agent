from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from plugins.park_security.server.models import SecurityAlarm, parse_timestamp


@dataclass(frozen=True)
class CorrelatedAlarmGroup:
    """A time-and-space-associated alarm group with a classified scenario."""

    scenario: str
    alarms: tuple[SecurityAlarm, ...]


class EventCorrelator:
    """Correlate raw alarms by park, building, area, and a fixed time window."""

    _REQUIRED_ALARM_TYPES = {
        "night_abnormal_access": {"after_hours_access", "person_detected"},
        "access_failure_and_loitering": {
            "repeated_access_failure",
            "loitering_report",
            "loitering_detected",
        },
        "fire_alarm_and_equipment_fault": {
            "smoke_detected",
            "temperature_rise",
            "ventilation_device_fault",
        },
    }

    def __init__(
        self,
        window: timedelta = timedelta(minutes=10),
        area_adjacency: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self.window = window
        self.area_adjacency = {
            area: set(neighbors) | {area}
            for area, neighbors in (area_adjacency or {}).items()
        }
        for area, neighbors in list(self.area_adjacency.items()):
            for neighbor in neighbors:
                self.area_adjacency.setdefault(neighbor, {neighbor}).add(area)

    def correlate(self, alarms: Iterable[SecurityAlarm]) -> list[CorrelatedAlarmGroup]:
        spatial_groups = self._spatial_groups(alarms)
        correlated: list[CorrelatedAlarmGroup] = []
        for spatial_alarms in spatial_groups:
            ordered = sorted(spatial_alarms, key=self._occurred_at)
            seen_groups: set[tuple[str, tuple[str, ...]]] = set()
            for index, anchor in enumerate(ordered):
                window_end = self._occurred_at(anchor) + self.window
                candidates = [
                    alarm
                    for alarm in ordered[index:]
                    if self._occurred_at(alarm) <= window_end
                ]
                for group in self._classify(candidates):
                    key = (group.scenario, tuple(sorted(alarm.alarm_id for alarm in group.alarms)))
                    if key not in seen_groups:
                        correlated.append(group)
                        seen_groups.add(key)

        return sorted(correlated, key=lambda group: self._occurred_at(group.alarms[0]))

    def _spatial_groups(
        self, alarms: Iterable[SecurityAlarm]
    ) -> list[list[SecurityAlarm]]:
        pending = [alarm.model_copy(deep=True) for alarm in alarms]
        groups: list[list[SecurityAlarm]] = []
        while pending:
            group = [pending.pop(0)]
            changed = True
            while changed:
                changed = False
                remaining: list[SecurityAlarm] = []
                for alarm in pending:
                    if any(self._spatially_related(alarm, member) for member in group):
                        group.append(alarm)
                        changed = True
                    else:
                        remaining.append(alarm)
                pending = remaining
            groups.append(group)
        return groups

    def _spatially_related(self, left: SecurityAlarm, right: SecurityAlarm) -> bool:
        if (left.park_id, left.building_id) != (right.park_id, right.building_id):
            return False
        if left.area_id == right.area_id:
            return True
        if left.area_id is None or right.area_id is None:
            return False
        return right.area_id in self.area_adjacency.get(left.area_id, {left.area_id})

    @classmethod
    def _classify(cls, alarms: list[SecurityAlarm]) -> list[CorrelatedAlarmGroup]:
        alarm_types = {alarm.alarm_type for alarm in alarms}
        groups: list[CorrelatedAlarmGroup] = []
        for scenario, required_types in cls._REQUIRED_ALARM_TYPES.items():
            if required_types <= alarm_types:
                by_association: dict[str, dict[str, SecurityAlarm]] = {}
                for alarm in alarms:
                    if alarm.alarm_type not in required_types:
                        continue
                    for association in cls._associations(alarm):
                        by_association.setdefault(association, {}).setdefault(
                            alarm.alarm_type, alarm
                        )
                matching = next(
                    (
                        selected
                        for selected in by_association.values()
                        if required_types <= selected.keys()
                    ),
                    None,
                )
                if matching is not None:
                    selected_ids = {alarm.alarm_id for alarm in matching.values()}
                    groups.append(
                        CorrelatedAlarmGroup(
                            scenario=scenario,
                            alarms=tuple(
                                alarm
                                for alarm in alarms
                                if alarm.alarm_id in selected_ids
                            ),
                        )
                    )
        return groups

    @staticmethod
    def _associations(alarm: SecurityAlarm) -> set[str]:
        associations: set[str] = set()
        for key in ("subject_id", "person_id", "device_group_id", "correlation_id"):
            value = alarm.payload.get(key)
            if isinstance(value, str) and value.strip():
                associations.add(f"{key}:{value.strip()}")
        if alarm.device_id:
            associations.add(f"device_id:{alarm.device_id}")
        return associations

    @staticmethod
    def _occurred_at(alarm: SecurityAlarm) -> datetime:
        return parse_timestamp(alarm.occurred_at)
