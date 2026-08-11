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
    """按园区、楼宇、区域、时间窗口和关联键归并原始告警。"""

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
        """初始化时间窗口和区域邻接关系；邻接关系会自动补齐反向边。"""
        self.window = window
        self.area_adjacency = {
            area: set(neighbors) | {area}
            for area, neighbors in (area_adjacency or {}).items()
        }
        for area, neighbors in list(self.area_adjacency.items()):
            for neighbor in neighbors:
                self.area_adjacency.setdefault(neighbor, {neighbor}).add(area)

    def correlate(self, alarms: Iterable[SecurityAlarm]) -> list[CorrelatedAlarmGroup]:
        """按空间、时间和主体/设备关联键归并告警，并去除重复匹配。"""
        spatial_groups = self._spatial_groups(alarms)
        correlated: list[CorrelatedAlarmGroup] = []
        for spatial_alarms in spatial_groups:
            ordered = sorted(spatial_alarms, key=self._occurred_at)
            for index, anchor in enumerate(ordered):
                window_end = self._occurred_at(anchor) + self.window
                candidates = [
                    alarm
                    for alarm in ordered[index:]
                    if self._occurred_at(alarm) <= window_end
                    and self._spatially_related(anchor, alarm)
                ]
                for group in self._classify(candidates):
                    merged = False
                    for existing_index, existing in enumerate(correlated):
                        if not self._groups_can_merge(existing, group):
                            continue
                        alarm_ids = {
                            alarm.alarm_id
                            for alarm in (*existing.alarms, *group.alarms)
                        }
                        merged_alarms = tuple(
                            alarm for alarm in ordered if alarm.alarm_id in alarm_ids
                        )
                        correlated[existing_index] = CorrelatedAlarmGroup(
                            scenario=existing.scenario,
                            alarms=merged_alarms,
                        )
                        merged = True
                        break
                    if not merged:
                        correlated.append(group)

        return sorted(correlated, key=lambda group: self._occurred_at(group.alarms[0]))

    def _groups_can_merge(
        self, left: CorrelatedAlarmGroup, right: CorrelatedAlarmGroup
    ) -> bool:
        """仅合并同场景、同关联键且时间窗口相互重叠的候选组。"""
        if left.scenario != right.scenario:
            return False
        if not any(
            self._spatially_related(left_alarm, right_alarm)
            for left_alarm in left.alarms
            for right_alarm in right.alarms
        ):
            return False
        left_keys = set.intersection(*(self._associations(alarm) for alarm in left.alarms))
        right_keys = set.intersection(*(self._associations(alarm) for alarm in right.alarms))
        if not left_keys.intersection(right_keys):
            return False
        left_start = self._occurred_at(left.alarms[0])
        left_end = self._occurred_at(left.alarms[-1])
        right_start = self._occurred_at(right.alarms[0])
        right_end = self._occurred_at(right.alarms[-1])
        return left_start <= right_end + self.window and right_start <= left_end + self.window

    def _spatial_groups(
        self, alarms: Iterable[SecurityAlarm]
    ) -> list[list[SecurityAlarm]]:
        """将同园区同楼宇且位于相同/相邻区域的告警组成空间连通分组。"""
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
        """判断两条告警是否属于同一空间范围。"""
        if (left.park_id, left.building_id) != (right.park_id, right.building_id):
            return False
        if left.area_id == right.area_id:
            return True
        if left.area_id is None or right.area_id is None:
            return False
        return right.area_id in self.area_adjacency.get(left.area_id, {left.area_id})

    @classmethod
    def _classify(cls, alarms: list[SecurityAlarm]) -> list[CorrelatedAlarmGroup]:
        """按场景所需告警类型和共享关联键生成一个或多个候选事件。"""
        alarm_types = {alarm.alarm_type for alarm in alarms}
        groups: list[CorrelatedAlarmGroup] = []
        for scenario, required_types in cls._REQUIRED_ALARM_TYPES.items():
            if required_types <= alarm_types:
                by_association: dict[str, list[SecurityAlarm]] = {}
                for alarm in alarms:
                    if alarm.alarm_type not in required_types:
                        continue
                    for association in cls._associations(alarm):
                        by_association.setdefault(association, []).append(alarm)
                for associated_alarms in by_association.values():
                    associated_types = {alarm.alarm_type for alarm in associated_alarms}
                    if not required_types <= associated_types:
                        continue
                    selected_ids = {alarm.alarm_id for alarm in associated_alarms}
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
        """提取主体、设备组、关联号和设备号等可用于关联的键。"""
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
        """把告警时间解析为带时区的 datetime，避免按字符串比较。"""
        return parse_timestamp(alarm.occurred_at)
