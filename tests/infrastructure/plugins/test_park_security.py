from __future__ import annotations

import asyncio
from datetime import datetime
import inspect

import pytest
from pydantic import ValidationError

from plugins.park_security.server.config import Settings
from plugins.park_security.server.models import (
    CreateWorkOrder,
    EventAction,
    EventListQuery,
    SecurityAlarm,
    SecurityEvent,
)
from plugins.park_security.server.mock_repository import MockSecurityRepository
from plugins.park_security.server.service import SecurityService


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


def test_settings_defaults_to_loopback_mock(monkeypatch):
    monkeypatch.delenv("PARK_SECURITY_MCP_HOST", raising=False)
    monkeypatch.delenv("PARK_SECURITY_DATA_MODE", raising=False)

    settings = Settings.from_env()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8200
    assert settings.data_mode == "mock"


def test_settings_rejects_non_mock_data_mode(monkeypatch):
    monkeypatch.setenv("PARK_SECURITY_DATA_MODE", "rest")

    with pytest.raises(ValueError, match="PARK_SECURITY_DATA_MODE must be mock"):
        Settings.from_env()


def test_action_models_require_operator_and_assignee():
    assert EventAction(event_id="event-night-001", operator_id="guard-01").operator_id == "guard-01"
    assert CreateWorkOrder(
        event_id="event-night-001", operator_id="guard-01", assignee="team-night"
    ).assignee == "team-night"


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


def test_service_exposes_shift_context_in_response_envelope():
    """Catch a service that leaks bare repository context instead of the public envelope."""
    service = SecurityService(MockSecurityRepository())

    context = asyncio.run(service.get_shift_context("park-1", "area-lab-01"))

    assert context["success"] is True
    assert context["data"]["focus_area"] == "area-lab-01"
    assert context["raw"] == context["data"]


def test_service_requires_confirmation_before_work_order_and_records_audit():
    """Catch skipped state validation, persistence, audit entries, or review report creation."""
    service = SecurityService(MockSecurityRepository())
    action = EventAction(event_id="event-night-001", operator_id="guard-01", note="现场核验")
    work_order_action = CreateWorkOrder(**action.model_dump(), assignee="team-night")

    with pytest.raises(ValueError, match="event_not_confirmed"):
        asyncio.run(service.create_work_order(work_order_action))
    confirmed = asyncio.run(service.confirm_event(action))
    created = asyncio.run(service.create_work_order(work_order_action))
    closed = asyncio.run(service.close_event(action))

    assert confirmed["data"]["status"] == "confirmed"
    assert created["data"]["status"] == "work_order_created"
    assert [record["action"] for record in closed["data"]["audit_records"]] == [
        "event_created", "confirmed", "work_order_created", "closed"
    ]
    assert closed["data"]["status"] == "closed"
    assert closed["data"]["review_report"] == {
        "event_id": "event-night-001",
        "final_risk_level": "high",
        "handling_process": ["event_created", "confirmed", "work_order_created", "closed"],
        "evidence_completeness": 0.92,
        "closed_at": "2026-08-11T01:30:00Z",
    }


def test_service_rejects_invalid_closure_states_and_missing_events():
    """Catch closure from open events and missing-event handling that returns partial data."""
    service = SecurityService(MockSecurityRepository())
    action = EventAction(event_id="event-access-002", operator_id="guard-01")

    with pytest.raises(ValueError, match="event_not_closable"):
        asyncio.run(service.close_event(action))
    with pytest.raises(ValueError, match="event_not_found"):
        asyncio.run(service.get_event_detail("event-unknown"))
