from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from plugins.park_security.server.config import Settings
from plugins.park_security.server.models import (
    CreateWorkOrder,
    EventAction,
    SecurityAlarm,
    SecurityEvent,
)
from plugins.park_security.server.mock_repository import MockSecurityRepository


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
