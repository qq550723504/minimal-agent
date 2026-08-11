from __future__ import annotations

import pytest
from pydantic import ValidationError

from plugins.park_security.server.config import Settings
from plugins.park_security.server.models import (
    CreateWorkOrder,
    EventAction,
    SecurityAlarm,
    SecurityEvent,
)


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
