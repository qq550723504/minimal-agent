import json

import pytest
from pydantic import ValidationError

from src.agent.llm import (
    ToolCallPlan,
    normalize_plan_items,
    parse_plan_output,
    parse_structured_plan_output,
)


def test_parse_structured_plan_output_returns_validated_tool_call():
    items = parse_structured_plan_output(
        '[{"kind":"tool_call","call_id":"call-1","tool":"energy.query_trend","arguments":{"park_id":"park-a"}}]'
    )

    assert isinstance(items[0], ToolCallPlan)
    assert items[0].tool == "energy.query_trend"
    assert items[0].arguments == {"park_id": "park-a"}


def test_parse_plan_output_json_array():
    output = '["Review requirements", "Draft architecture", "Validate deployment"]'
    parsed = parse_plan_output(output)
    assert parsed == ["Review requirements", "Draft architecture", "Validate deployment"]


def test_parse_plan_output_structured_objects():
    output = '[{"tool": "http_get", "payload": {"url": "https://api.example.com/data"}}, "Verify results"]'
    parsed = parse_plan_output(output)
    assert parsed == [
        {"tool": "http_get", "payload": {"url": "https://api.example.com/data"}},
        "Verify results",
    ]


def test_parse_plan_output_preserves_legacy_dictionary_shape():
    parsed = parse_plan_output('[{"tool":"legacy","payload":"x"}]')

    assert parsed == [{"tool": "legacy", "payload": "x"}]


def test_normalize_plan_items_validates_tool_calls_and_serializes_text_safe_dicts():
    items = normalize_plan_items(
        [
            {"kind": "tool_call", "call_id": "call-1", "tool": "demo.read", "arguments": {"id": "x"}},
            "Verify results",
            {"tool": "legacy", "payload": "x"},
        ]
    )

    assert isinstance(items[0], ToolCallPlan)
    assert items[1] == "Verify results"
    assert items[2] == json.dumps({"tool": "legacy", "payload": "x"}, ensure_ascii=False, sort_keys=True)


def test_normalize_plan_items_rejects_extra_fields():
    with pytest.raises(ValidationError):
        normalize_plan_items(
            [
                {
                    "kind": "tool_call",
                    "call_id": "call-1",
                    "tool": "demo.read",
                    "arguments": {},
                    "unexpected": True,
                }
            ]
        )


def test_normalize_plan_items_rejects_non_object_arguments():
    with pytest.raises(ValidationError):
        normalize_plan_items(
            [
                {
                    "kind": "tool_call",
                    "call_id": "call-1",
                    "tool": "demo.read",
                    "arguments": ["bad"],
                }
            ]
        )


def test_normalize_plan_items_rejects_empty_call_ids():
    with pytest.raises(ValidationError):
        normalize_plan_items(
            [
                {
                    "kind": "tool_call",
                    "call_id": "",
                    "tool": "demo.read",
                    "arguments": {},
                }
            ]
        )


def test_normalize_plan_items_rejects_invalid_tool_names():
    with pytest.raises(ValidationError):
        normalize_plan_items(
            [
                {
                    "kind": "tool_call",
                    "call_id": "call-1",
                    "tool": "Energy.Read",
                    "arguments": {},
                }
            ]
        )


def test_parse_structured_plan_output_handles_text_and_tool_calls():
    items = parse_structured_plan_output(
        '[{"kind":"tool_call","call_id":"call-1","tool":"demo.read","arguments":{"id":"x"}}, "Verify results"]'
    )

    assert isinstance(items[0], ToolCallPlan)
    assert items[1] == "Verify results"


def test_parse_structured_plan_output_serializes_invalid_tool_calls_as_text():
    payload = {
        "kind": "tool_call",
        "call_id": "call-1",
        "tool": "Energy.Read",
        "arguments": {},
    }

    assert parse_structured_plan_output(json.dumps([payload])) == [
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    ]


def test_parse_structured_plan_output_falls_back_for_malformed_json():
    assert parse_structured_plan_output("[{\"kind\":\"tool_call\"") == ['[{"kind":"tool_call"']


def test_parse_plan_output_text_fallback():
    output = "Review requirements. Draft architecture. Validate deployment."
    parsed = parse_plan_output(output)
    assert parsed == ["Review requirements", "Draft architecture", "Validate deployment"]


def test_parse_plan_output_line_breaks():
    output = "Collect requirements\nDraft architecture\nValidate deployment"
    parsed = parse_plan_output(output)
    assert parsed == ["Collect requirements", "Draft architecture", "Validate deployment"]


def test_parse_plan_output_invalid_json():
    output = "[Review requirements, Draft architecture]"
    parsed = parse_plan_output(output)
    assert parsed == ["[Review requirements, Draft architecture]"]
