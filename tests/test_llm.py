import json

from src.agent.llm import parse_plan_output


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
