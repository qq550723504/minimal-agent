      function evidence(id, source, occurredAt, summary, reference) {
        return { evidence_id: id, source, occurred_at: occurredAt, summary, reference };
      }

export function createInitialEvents() {
        return [
          {
            event_id: "event-night-001", park_id: "park-1", building_id: "building-a", area_id: "area-lab-01",
            scenario: "night_abnormal_access", risk_level: "high", status: "open",
            first_occurred_at: "2026-08-11T00:12:00Z", last_occurred_at: "2026-08-11T00:14:00Z",
            alarm_ids: ["alarm-access-001", "alarm-video-001"], impact_scope: ["building-a", "area-lab-01", "night-research-zone"],
            recommended_plan: "night_access_verification", responsible_party: "team-night", evidence_completeness: .92,
            timeline: [
              evidence("evidence-night-access", "access_control", "2026-08-11T00:12:00Z", "夜间门禁尝试被拒绝。", "access://door-lab-01/log/001"),
              evidence("evidence-night-video", "video", "2026-08-11T00:14:00Z", "实验室门附近检测到人员。", "s3://park-security/screenshots/night-001.jpg"),
              evidence("evidence-night-shift", "shift", "2026-08-11T00:15:00Z", "Guard-01 被分配到北侧巡逻路线。", "shift://2026-08-11/guard-01"),
              evidence("evidence-night-appointment", "appointment", "2026-08-11T00:15:00Z", "没有匹配到有效访客预约。", "appointment://lab-01/lookup/001")
            ],
            audit_records: [{ audit_id: "audit-night-001", operator_id: "guard-01", action: "event_created", occurred_at: "2026-08-11T00:15:00Z", note: "" }],
            work_order_id: null, work_orders: [], confirmed_at: null, closed_at: null
          },
          {
            event_id: "event-access-002", park_id: "park-1", building_id: "building-a", area_id: "area-gate-02",
            scenario: "access_failure_and_loitering", risk_level: "high", status: "open",
            first_occurred_at: "2026-08-11T00:42:00Z", last_occurred_at: "2026-08-11T00:49:00Z",
            alarm_ids: ["alarm-access-002", "alarm-patrol-001", "alarm-video-002"], impact_scope: ["building-a", "area-gate-02", "visitor-entry-route"],
            recommended_plan: "verify_visitor_appointment_and_dispatch_patrol", responsible_party: "team-access", evidence_completeness: .88,
            timeline: [
              evidence("evidence-access-reader", "access_control", "2026-08-11T00:42:00Z", "记录到 3 次凭证失败。", "access://gate-reader-02/log/002"),
              evidence("evidence-access-patrol", "patrol", "2026-08-11T00:47:00Z", "巡更报告门禁拒绝后仍有人徘徊。", "patrol://patrol-point-02/report/002"),
              evidence("evidence-access-video", "video", "2026-08-11T00:49:00Z", "视频检测到人员持续停留在入口。", "s3://park-security/screenshots/access-002.jpg"),
              evidence("evidence-access-appointment", "appointment", "2026-08-11T00:50:00Z", "没有匹配到有效访客预约。", "appointment://gate-02/lookup/002")
            ],
            audit_records: [{ audit_id: "audit-access-002", operator_id: "guard-01", action: "event_created", occurred_at: "2026-08-11T00:50:00Z", note: "" }],
            work_order_id: null, work_orders: [], confirmed_at: null, closed_at: null
          },
          {
            event_id: "event-fire-003", park_id: "park-1", building_id: "building-a", area_id: "area-plant-01",
            scenario: "fire_alarm_and_equipment_fault", risk_level: "critical", status: "open",
            first_occurred_at: "2026-08-11T01:02:00Z", last_occurred_at: "2026-08-11T01:04:00Z",
            alarm_ids: ["alarm-fire-001", "alarm-fire-002", "alarm-fire-003"], impact_scope: ["building-a", "area-plant-01", "mechanical-room", "evacuation-zone-a"],
            recommended_plan: "fire_emergency_response", responsible_party: "team-fire", evidence_completeness: .97,
            timeline: [
              evidence("evidence-fire-smoke", "fire", "2026-08-11T01:02:00Z", "机房烟感触发报警。", "fire://smoke-plant-01/event/003"),
              evidence("evidence-fire-temperature", "fire", "2026-08-11T01:03:00Z", "温度升高并超过消防阈值。", "fire://temp-plant-01/event/003"),
              evidence("evidence-fire-device", "device", "2026-08-11T01:04:00Z", "通风风机上报故障状态。", "device://fan-plant-01/status/003")
            ],
            audit_records: [{ audit_id: "audit-fire-003", operator_id: "guard-01", action: "event_created", occurred_at: "2026-08-11T01:05:00Z", note: "" }],
            work_order_id: null, work_orders: [], confirmed_at: null, closed_at: null
          }
        ];
      }

export const shiftContext = {
        park_id: "park-1", focus_area: "area-lab-01", query_time: "2026-08-11T01:00:00Z", on_duty: true,
        key_areas: ["area-lab-01", "area-gate-02", "area-plant-01"],
        on_duty_guard: { guard_id: "guard-01", name: "Li Wei", shift: "night", shift_start: "2026-08-10T16:00:00Z", shift_end: "2026-08-11T08:00:00Z" },
        responsible_areas: ["area-lab-01", "area-gate-02", "area-plant-01"],
        escalation_rules: {
          level_1: { condition: "高风险或门禁异常", notify: ["guard-01", "team-night"], response_within_minutes: 5 },
          level_2: { condition: "严重消防或生命安全告警", notify: ["team-fire", "park-manager", "emergency-services"], response_within_minutes: 1 }
        }
      };


