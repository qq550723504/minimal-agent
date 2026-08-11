import json


class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"text": "第一句。第二句?"})()


class EmptyGeminiModels:
    def generate_content(self, **kwargs):
        return type("Response", (), {"text": None})()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


class StructuredGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if "config" not in kwargs:
            return type("Response", (), {"text": "请调用 energy.query_trend 查询能耗。"})()
        response_schema = kwargs["config"].response_json_schema
        arguments_schema = response_schema["items"]["anyOf"][1]["properties"]["arguments"]
        arguments = {}
        if "park_id" in arguments_schema.get("properties", {}):
            arguments = {
                "park_id": "park-1",
                "start_time": "2026-08-10T00:00:00+08:00",
                "end_time": "2026-08-10T23:59:59+08:00",
            }
        return type(
            "Response",
            (),
            {
                "text": json.dumps(
                    [
                        {
                            "kind": "tool_call",
                            "call_id": "call-1",
                            "tool": "energy.query_trend",
                            "arguments": arguments,
                        }
                    ]
                )
            },
        )()


def test_gemini_adapter_uses_generate_content_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = FakeGeminiClient()

    from src.agent.infrastructure.llm.llm_gemini import GeminiAdapter

    adapter = GeminiAdapter(model="gemini-test", client=client)

    assert adapter.plan("任何提示") == ["echo: 第一句", "echo: 第二句"]
    assert client.models.calls == [
        {"model": "gemini-test", "contents": "任何提示"}
    ]


def test_gemini_adapter_returns_empty_plan_without_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = type("Client", (), {"models": EmptyGeminiModels()})()

    from src.agent.infrastructure.llm.llm_gemini import GeminiAdapter

    adapter = GeminiAdapter(model="gemini-test", client=client)

    assert adapter.plan("会被安全策略拦截的提示") == []


def test_gemini_adapter_enforces_json_for_structured_planning(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    models = StructuredGeminiModels()
    client = type("Client", (), {"models": models})()

    from src.agent.infrastructure.llm.llm_gemini import GeminiAdapter

    adapter = GeminiAdapter(model="gemini-test", client=client)
    result = adapter.plan(
        "Tool catalog: "
        + json.dumps(
            [
                {
                    "name": "energy.query_trend",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "park_id": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                        },
                        "required": ["park_id", "start_time", "end_time"],
                    },
                }
            ]
        )
        + "\n"
        "Response contract:\n"
        "Return only a JSON array."
    )

    assert result[0]["kind"] == "tool_call"
    assert result[0]["tool"] == "energy.query_trend"
    assert result[0]["arguments"]["park_id"] == "park-1"
    request_config = models.calls[0]["config"]
    assert request_config.response_mime_type == "application/json"
    assert request_config.response_schema is None
    response_schema = request_config.response_json_schema
    assert response_schema["type"] == "array"
    tool_call_schema = response_schema["items"]["anyOf"][1]
    assert "additionalProperties" not in tool_call_schema
    assert "additionalProperties" not in tool_call_schema["properties"]["arguments"]
