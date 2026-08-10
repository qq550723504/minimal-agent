import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from src.agent.domain.planning.models import ToolCallPlan, normalize_plan_items


def test_tool_call_plan_validates_lowercase_tool_name():
    plan = ToolCallPlan.model_validate(
        {
            "kind": "tool_call",
            "call_id": "call-1",
            "tool": "energy.query_trend",
            "arguments": {"park_id": "park-a"},
        }
    )

    assert plan.tool == "energy.query_trend"
    assert plan.arguments == {"park_id": "park-a"}


def test_tool_call_plan_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ToolCallPlan.model_validate(
            {
                "kind": "tool_call",
                "call_id": "call-1",
                "tool": "energy.query_trend",
                "arguments": {},
                "unexpected": True,
            }
        )


def test_tool_call_plan_rejects_empty_call_id():
    with pytest.raises(ValidationError):
        ToolCallPlan.model_validate(
            {
                "kind": "tool_call",
                "call_id": "",
                "tool": "energy.query_trend",
                "arguments": {},
            }
        )


def test_tool_call_plan_rejects_invalid_tool_name():
    with pytest.raises(ValidationError):
        ToolCallPlan.model_validate(
            {
                "kind": "tool_call",
                "call_id": "call-1",
                "tool": "Energy.Query",
                "arguments": {},
            }
        )


def test_structured_tool_calling_flag_defaults_false():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.agent.config import STRUCTURED_TOOL_CALLING_ENABLED; print(STRUCTURED_TOOL_CALLING_ENABLED)",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False"


def test_structured_tool_calling_flag_can_be_enabled():
    environment = os.environ | {"AGENT_STRUCTURED_TOOL_CALLING_ENABLED": "true"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.agent.config import STRUCTURED_TOOL_CALLING_ENABLED; print(STRUCTURED_TOOL_CALLING_ENABLED)",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "True"


def test_normalize_plan_items_preserves_text_items():
    assert normalize_plan_items(["first step", "second step"]) == ["first step", "second step"]
