from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest
import yaml
from pydantic import ValidationError

from plugins.park_security.server.config import Settings
from plugins.park_security.server.models import (
    CloseEventAction,
    CreateWorkOrder,
    EventAction,
    EventListQuery,
    EventStatus,
    RiskLevel,
    SecurityAlarm,
    SecurityEvent,
)
from plugins.park_security.server.mock_repository import (
    EventCorrelator,
    MockSecurityRepository,
    RiskAssessor,
)
from plugins.park_security.server.service import SecurityService


def test_compose_wires_agent_to_park_security_service():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    agent = compose["services"]["agent"]
    security = compose["services"]["park_security"]

    assert (
        agent["environment"]["PARK_SECURITY_MCP_URL"]
        == "${PARK_SECURITY_MCP_URL:-http://park_security:8200/mcp}"
    )
    assert agent["depends_on"]["park_security"]["condition"] == "service_healthy"
    assert security["environment"]["PARK_SECURITY_DATA_MODE"] == "${PARK_SECURITY_DATA_MODE:-mock}"
    assert "PARK_SECURITY_APPROVAL_TOKEN" not in agent["environment"]
    assert (
        security["environment"]["PARK_SECURITY_APPROVAL_TOKEN"]
        == "${PARK_SECURITY_APPROVAL_TOKEN:-}"
    )


def test_mcp_handlers_have_explicit_parameters_and_expected_names():
    from mcp.server import MCPServer
    from plugins.park_security.server.main import (
        close_event,
        confirm_event,
        create_work_order,
        get_event_detail,
        get_event_summary,
        get_shift_context,
        list_events,
        mcp,
    )

    handlers = [
        get_event_summary,
        list_events,
        get_event_detail,
        get_shift_context,
        confirm_event,
        create_work_order,
        close_event,
    ]
    assert isinstance(mcp, MCPServer)
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for handler in handlers
        for parameter in inspect.signature(handler).parameters.values()
    )
    assert "operator_id" in inspect.signature(confirm_event).parameters
    assert "assignee" in inspect.signature(create_work_order).parameters
    assert all(
        "approval_token" in inspect.signature(handler).parameters
        for handler in (confirm_event, create_work_order, close_event)
    )
    assert inspect.signature(close_event).parameters["note"].default is inspect.Parameter.empty


def test_settings_defaults_to_loopback_mock(monkeypatch):
    monkeypatch.delenv("PARK_SECURITY_MCP_HOST", raising=False)
    monkeypatch.delenv("PARK_SECURITY_DATA_MODE", raising=False)
    monkeypatch.delenv("PARK_SECURITY_APPROVAL_TOKEN", raising=False)

    settings = Settings.from_env()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8200
    assert settings.data_mode == "mock"
    assert settings.approval_token is None


def test_mcp_filter_schema_uses_domain_literal_types():
    from plugins.park_security.server.main import list_events

    hints = get_type_hints(list_events)
    assert hints["risk_level"] == RiskLevel | None
    assert hints["status"] == EventStatus | None


def test_settings_rejects_non_mock_data_mode(monkeypatch):
    monkeypatch.setenv("PARK_SECURITY_DATA_MODE", "rest")

    with pytest.raises(ValueError, match="PARK_SECURITY_DATA_MODE must be mock"):
        Settings.from_env()


def test_action_models_require_operator_and_assignee():
    action = EventAction(
        event_id="event-night-001",
        operator_id="  guard-01  ",
        approval_token="  approved  ",
    )
    work_order = CreateWorkOrder(
        event_id="event-night-001",
        operator_id="guard-01",
        assignee="  team-night  ",
        approval_token="approved",
    )

    assert action.operator_id == "guard-01"
    assert action.approval_token == "approved"
    assert work_order.assignee == "team-night"


@pytest.mark.parametrize("field", ["operator_id", "approval_token"])
def test_event_action_rejects_blank_credentials(field):
    values = {
        "event_id": "event-night-001",
        "operator_id": "guard-01",
        "approval_token": "approved",
    }
    values[field] = "   "

    with pytest.raises(ValidationError):
        EventAction(**values)


def test_create_work_order_rejects_blank_assignee():
    with pytest.raises(ValidationError):
        CreateWorkOrder(
            event_id="event-night-001",
            operator_id="guard-01",
            assignee="  ",
            approval_token="approved",
        )


def test_close_event_requires_non_blank_disposition_note():
    with pytest.raises(ValidationError):
        CloseEventAction(
            event_id="event-night-001",
            operator_id="guard-01",
            approval_token="approved",
            note="  ",
        )


def test_security_event_defaults_to_open_with_empty_collections():
    event = SecurityEvent.model_validate({"event_id": "event-night-001", "park_id": "park-1"})

    assert event.status == "open"
    assert event.alarm_ids == []
    assert event.timeline == []
    assert event.audit_records == []


def test_alarm_source_is_limited_to_upstream_security_systems():
    with pytest.raises(ValidationError):
        SecurityAlarm(alarm_id="alarm-001", source="device", park_id="park-1")


def test_security_event_rejects_empty_alarm_identifiers():
    with pytest.raises(ValidationError):
        SecurityEvent(event_id="event-001", park_id="park-1", alarm_ids=[""])


def test_repository_exposes_three_correlated_mock_scenarios():
    events = MockSecurityRepository().list_events("park-1")

    assert [event.event_id for event in events] == [
        "event-night-001",
        "event-access-002",
        "event-fire-003",
    ]
    night, access, fire = events
    assert night.scenario == "night_abnormal_access"
    assert night.risk_level == "high"
    assert len(night.alarm_ids) == 2
    assert access.scenario == "access_failure_and_loitering"
    assert len(access.alarm_ids) == 3
    assert fire.risk_level == "critical"
    assert {item.source for item in fire.timeline} >= {"fire", "device"}


def test_correlator_and_risk_assessor_are_independently_callable():
    alarms = [
        SecurityAlarm(
            alarm_id="access-1",
            source="access_control",
            park_id="park-test",
            building_id="building-test",
            area_id="area-test",
            occurred_at="2026-08-11T02:00:00Z",
            alarm_type="repeated_access_failure",
            severity="medium",
            payload={"attempt_count": 1},
        ),
        SecurityAlarm(
            alarm_id="patrol-1",
            source="patrol",
            park_id="park-test",
            building_id="building-test",
            area_id="area-test",
            occurred_at="2026-08-11T02:04:00Z",
            alarm_type="loitering_report",
            severity="medium",
        ),
        SecurityAlarm(
            alarm_id="video-1",
            source="video",
            park_id="park-test",
            building_id="building-test",
            area_id="area-test",
            occurred_at="2026-08-11T02:06:00Z",
            alarm_type="loitering_detected",
            severity="medium",
        ),
    ]

    groups = EventCorrelator().correlate(alarms)
    assessment = RiskAssessor().assess(groups[0])

    assert len(groups) == 1
    assert groups[0].scenario == "access_failure_and_loitering"
    assert [alarm.alarm_id for alarm in groups[0].alarms] == [
        "access-1",
        "patrol-1",
        "video-1",
    ]
    assert assessment.risk_level == "medium"
    assert assessment.recommended_plan == "verify_visitor_appointment_and_dispatch_patrol"


def test_correlator_compares_alarm_instants_when_offsets_differ():
    alarms = [
        SecurityAlarm(
            alarm_id="late-access",
            source="access_control",
            park_id="park-test",
            building_id="building-test",
            area_id="area-test",
            occurred_at="2026-08-10T23:59:00-10:00",
            alarm_type="after_hours_access",
            severity="high",
        ),
        SecurityAlarm(
            alarm_id="early-video",
            source="video",
            park_id="park-test",
            building_id="building-test",
            area_id="area-test",
            occurred_at="2026-08-11T00:00:00+10:00",
            alarm_type="person_detected",
            severity="high",
        ),
    ]

    assert EventCorrelator().correlate(alarms) == []


def test_access_event_detail_includes_patrol_evidence():
    detail = asyncio.run(SecurityService(MockSecurityRepository()).get_event_detail(
        "event-access-002"
    ))

    assert any(item["source"] == "patrol" for item in detail["data"]["timeline"])


def test_repository_returns_deep_copies_when_reading_and_saving_events():
    repository = MockSecurityRepository()

    event = repository.get_event("event-night-001")
    assert event is not None
    event.timeline[0].summary = "altered by caller"
    assert repository.get_event("event-night-001").timeline[0].summary != "altered by caller"

    saved = repository.save_event(event)
    saved.recommended_plan = "altered after save"
    assert repository.get_event("event-night-001").recommended_plan != "altered after save"


def test_repository_creates_one_stable_work_order_per_event():
    repository = MockSecurityRepository()

    work_order = repository.create_work_order(
        "event-access-002", "team-access", "guard-01", "dispatch technician"
    )

    assert work_order.work_order_id == "wo-event-access-002"
    assert work_order.event_id == "event-access-002"
    assert work_order.status == "open"
    assert repository.get_event("event-access-002").work_order_id == "wo-event-access-002"
    with pytest.raises(ValueError, match="work_order_exists"):
        repository.create_work_order("event-access-002", "team-access", "guard-01", None)


def test_repository_exposes_shift_context_for_requested_area():
    context = MockSecurityRepository().list_shift_context("park-1", "area-lab-01")

    assert context["focus_area"] == "area-lab-01"
    assert context["on_duty_guard"]["guard_id"] == "guard-01"
    assert "area-lab-01" in context["responsible_areas"]
    assert set(context["escalation_rules"]) == {"level_1", "level_2"}


def test_night_shift_covers_the_night_access_event_timeline():
    repository = MockSecurityRepository()
    event = repository.get_event("event-night-001")
    context = repository.list_shift_context("park-1", event.area_id)

    shift_start = datetime.fromisoformat(context["on_duty_guard"]["shift_start"])
    shift_end = datetime.fromisoformat(context["on_duty_guard"]["shift_end"])
    event_times = [
        datetime.fromisoformat(event.first_occurred_at),
        datetime.fromisoformat(event.last_occurred_at),
        *(datetime.fromisoformat(item.occurred_at) for item in event.timeline),
    ]

    assert all(shift_start <= occurred_at <= shift_end for occurred_at in event_times)


def test_service_returns_event_timeline_and_summary():
    """Catch a service that omits the repository's risk aggregation or event detail."""
    service = SecurityService(MockSecurityRepository())

    summary = asyncio.run(service.get_event_summary("park-1"))
    detail = asyncio.run(service.get_event_detail("event-fire-003"))

    assert summary["data"] == {
        "park_id": "park-1",
        "total_events": 3,
        "risk_counts": {"high": 2, "critical": 1},
        "status_counts": {"open": 3},
        "raw_alarm_count": 8,
        "merged_event_count": 3,
        "duplicate_alarm_count": 5,
        "effective_alarm_rate": 0.375,
        "average_risk_score": pytest.approx(3.3333333333333335),
    }
    assert detail["data"]["recommended_plan"] == "fire_emergency_response"
    assert len(detail["data"]["timeline"]) == 3
    assert {item["source"] for item in detail["data"]["timeline"]} == {"fire", "device"}


def test_service_filters_event_cards_by_every_query_condition():
    """Catch filtering that ignores a supplied time, risk, or status condition."""
    service = SecurityService(MockSecurityRepository())

    result = asyncio.run(service.list_events(EventListQuery(
        park_id="park-1",
        start_time="2026-08-11T00:20:00Z",
        end_time="2026-08-11T01:00:00Z",
        risk_level="high",
        status="open",
    )))

    assert result["data"] == [{
        "event_id": "event-access-002",
        "park_id": "park-1",
        "building_id": "building-a",
        "area_id": "area-gate-02",
        "scenario": "access_failure_and_loitering",
        "risk_level": "high",
        "status": "open",
        "first_occurred_at": "2026-08-11T00:42:00Z",
        "last_occurred_at": "2026-08-11T00:49:00Z",
        "impact_scope": ["building-a", "area-gate-02", "visitor-entry-route"],
        "recommended_plan": "verify_visitor_appointment_and_dispatch_patrol",
        "work_order_id": None,
    }]


def test_service_filters_event_cards_by_timestamp_instant_not_lexical_text():
    service = SecurityService(MockSecurityRepository())

    result = asyncio.run(service.list_events(EventListQuery(
        park_id="park-1",
        start_time="2026-08-11T09:00:00+08:00",
        end_time="2026-08-11T09:10:00+08:00",
    )))

    assert [event["event_id"] for event in result["data"]] == ["event-fire-003"]


def test_event_list_query_rejects_invalid_timestamps():
    with pytest.raises(ValidationError, match="valid ISO 8601 timestamp"):
        EventListQuery(park_id="park-1", start_time="not-a-timestamp")


def test_service_exposes_shift_context_in_response_envelope():
    """Catch a service that leaks bare repository context instead of the public envelope."""
    service = SecurityService(MockSecurityRepository())

    context = asyncio.run(service.get_shift_context(
        "park-1", "area-lab-01", "2026-08-11T01:00:00+00:00"
    ))

    assert context["success"] is True
    assert context["data"]["focus_area"] == "area-lab-01"
    assert context["raw"] == context["data"]
    assert context["data"]["query_time"] == "2026-08-11T01:00:00Z"
    assert context["data"]["on_duty"] is True


def test_shift_context_rejects_unknown_park_or_area():
    service = SecurityService(MockSecurityRepository())

    with pytest.raises(ValueError, match="park_not_found"):
        asyncio.run(service.get_shift_context("park-2", None))
    with pytest.raises(ValueError, match="area_not_found"):
        asyncio.run(service.get_shift_context("park-1", "area-unknown"))


def test_shift_context_returns_time_appropriate_duty_state():
    service = SecurityService(MockSecurityRepository())

    context = asyncio.run(service.get_shift_context(
        "park-1", "area-lab-01", "2026-08-11T10:00:00Z"
    ))

    assert context["data"]["query_time"] == "2026-08-11T10:00:00Z"
    assert context["data"]["on_duty"] is False
    assert context["data"]["on_duty_guard"] is None


def test_service_requires_confirmation_before_work_order_and_records_audit(monkeypatch):
    """Catch skipped state validation, persistence, audit entries, or review report creation."""
    monkeypatch.setenv("PARK_SECURITY_APPROVAL_TOKEN", "human-approved")
    service = SecurityService(MockSecurityRepository())
    action = EventAction(
        event_id="event-night-001",
        operator_id="guard-01",
        approval_token="human-approved",
        note="现场核验",
    )
    work_order_action = CreateWorkOrder(**action.model_dump(), assignee="team-night")
    close_action = CloseEventAction(
        **action.model_dump(exclude={"note"}), note="现已排除异常，恢复常态巡更"
    )

    with pytest.raises(ValueError, match="event_not_confirmed"):
        asyncio.run(service.create_work_order(work_order_action))
    confirmed = asyncio.run(service.confirm_event(action))
    created = asyncio.run(service.create_work_order(work_order_action))
    closed = asyncio.run(service.close_event(close_action))

    assert confirmed["data"]["status"] == "confirmed"
    assert created["data"]["status"] == "work_order_created"
    assert [record["action"] for record in closed["data"]["audit_records"]] == [
        "event_created", "confirmed", "work_order_created", "closed"
    ]
    assert closed["data"]["status"] == "closed"
    assert closed["data"]["work_orders"] == [{
        "work_order_id": "wo-event-night-001",
        "event_id": "event-night-001",
        "status": "closed",
        "assignee": "team-night",
        "operator_id": "guard-01",
        "created_at": "2026-08-11T01:20:00Z",
        "closed_at": "2026-08-11T01:30:00Z",
        "note": "现场核验",
    }]
    assert closed["data"]["review_report"] == {
        "event_id": "event-night-001",
        "final_risk_level": "high",
        "disposition": "现已排除异常，恢复常态巡更",
        "handling_process": ["event_created", "confirmed", "work_order_created", "closed"],
        "timeline": closed["data"]["timeline"],
        "evidence_completeness": 0.92,
        "closed_at": "2026-08-11T01:30:00Z",
    }


def test_write_actions_require_configured_matching_approval_token(monkeypatch):
    action = EventAction(
        event_id="event-night-001",
        operator_id="guard-01",
        approval_token="presented-token",
    )
    write_actions = [
        ("confirm_event", action),
        (
            "create_work_order",
            CreateWorkOrder(**action.model_dump(), assignee="team-night"),
        ),
        (
            "close_event",
            CloseEventAction(
                **action.model_dump(exclude={"note"}), note="现场处置完成"
            ),
        ),
    ]

    monkeypatch.delenv("PARK_SECURITY_APPROVAL_TOKEN", raising=False)
    for method_name, write_action in write_actions:
        service = SecurityService(MockSecurityRepository())
        with pytest.raises(ValueError, match="approval_not_configured"):
            asyncio.run(getattr(service, method_name)(write_action))

    monkeypatch.setenv("PARK_SECURITY_APPROVAL_TOKEN", "expected-token")
    for method_name, write_action in write_actions:
        service = SecurityService(MockSecurityRepository())
        with pytest.raises(ValueError, match="approval_denied"):
            asyncio.run(getattr(service, method_name)(write_action))

    approved_action = action.model_copy(update={"approval_token": "expected-token"})
    result = asyncio.run(SecurityService(MockSecurityRepository()).confirm_event(approved_action))
    assert result["data"]["status"] == "confirmed"


def test_service_rejects_invalid_closure_states_and_missing_events(monkeypatch):
    """Catch closure from open events and missing-event handling that returns partial data."""
    monkeypatch.setenv("PARK_SECURITY_APPROVAL_TOKEN", "human-approved")
    service = SecurityService(MockSecurityRepository())
    action = CloseEventAction(
        event_id="event-access-002",
        operator_id="guard-01",
        approval_token="human-approved",
        note="现场处置完成",
    )

    with pytest.raises(ValueError, match="event_not_closable"):
        asyncio.run(service.close_event(action))
    with pytest.raises(ValueError, match="event_not_found"):
        asyncio.run(service.get_event_detail("event-unknown"))
