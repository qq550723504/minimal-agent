import json

from src.agent.domain.capabilities.models import ToolSource, ToolSpec
from src.agent.infrastructure.memory.memory import get_global_memory
from src.agent.application.planning.service import build_tool_catalog_prompt, plan_task, _build_rag_prompt
from src.agent.infrastructure.llm.llm import MockLLM, LLMAdapter


def _catalog_from_prompt(prompt: str) -> list[dict]:
    catalog_json = prompt.split("Tool catalog:\n", 1)[1].split("\n\nResponse contract:", 1)[0]
    return json.loads(catalog_json)


def test_plan_with_mock_llm():
    llm = MockLLM()
    steps = plan_task("请总结并回复: 你好。请说明今天的任务。", llm=llm)
    # MockLLM 应把句子拆分成多个 echo 步骤
    assert all(s.startswith("echo: ") for s in steps)


def test_build_rag_prompt():
    prompt = "What is the capital of France?"
    memories = [
        {"text": "Paris is the capital of France.", "metadata": {"source": "wiki"}},
        {"text": "France has many regions."},
    ]

    result = _build_rag_prompt(prompt, memories)
    assert "Relevant memory:" in result
    assert "Paris is the capital of France." in result
    assert "Task:\nWhat is the capital of France?" in result


def test_build_rag_prompt_with_conversation_history():
    prompt = "Summarize the plan"
    memories = []
    history = [
        {"prompt": "第一步：收集需求。"},
        {"prompt": "第二步：设计架构。"},
    ]

    result = _build_rag_prompt(prompt, memories, history)
    assert "System:" in result
    assert "Conversation history:" in result
    assert "第一步：收集需求。" in result
    assert "Task:\nSummarize the plan" in result
    assert "Response format:" in result


def test_build_rag_prompt_structure():
    prompt = "Create a deployment checklist"
    memories = [
        {"text": "Deployment requires environment validation.", "metadata": {"source": "ops"}}
    ]
    result = _build_rag_prompt(prompt, memories)

    assert result.startswith("System:")
    assert "Relevant memory:" in result
    assert "Response format:" in result


def test_plan_task_includes_conversation_history():
    class RecordingLLM(LLMAdapter):
        def __init__(self):
            self.prompt = None

        def plan(self, prompt: str):
            self.prompt = prompt
            return [prompt]

    llm = RecordingLLM()
    mem = get_global_memory()
    mem.add("user42", {"prompt": "Earlier request about deployment."})

    steps = plan_task("Now summarize the deployment plan.", user_id="user42", llm=llm)
    assert steps == [llm.prompt]
    assert "Conversation history:" in llm.prompt
    assert "Earlier request about deployment." in llm.prompt
    assert "Task:\nNow summarize the deployment plan." in llm.prompt


def test_plan_task_skips_default_user_history(monkeypatch):
    class RecordingLLM(LLMAdapter):
        def __init__(self):
            self.prompt = None

        def plan(self, prompt: str):
            self.prompt = prompt
            return [prompt]

    llm = RecordingLLM()
    mem = get_global_memory()
    mem.add("default", {"prompt": "Earlier request about deployment."})
    monkeypatch.setattr("src.agent.application.planning.service.get_relevant_memory", lambda *args, **kwargs: [])

    steps = plan_task("Now summarize the deployment plan.", llm=llm)
    assert steps == [llm.prompt]
    assert "Conversation history:" not in llm.prompt
    assert "Earlier request about deployment." not in llm.prompt
    assert llm.prompt == "Now summarize the deployment plan."


def test_plan_task_passes_user_id_to_relevant_memory(monkeypatch):
    captured = {}

    def fake_relevant_memory(text, top_k=3, user_id=None):
        captured.update(text=text, top_k=top_k, user_id=user_id)
        return []

    monkeypatch.setattr("src.agent.application.planning.service.get_relevant_memory", fake_relevant_memory)
    plan_task("alice request", user_id="alice", llm=MockLLM())

    assert captured["user_id"] == "alice"


def test_build_tool_catalog_prompt_is_safe_and_sorted():
    spec_b = ToolSpec(
        name="b.tool",
        description="Second tool",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https://internal.example/api"},
                "token_env": {"type": "string", "description": "SECRET_TOKEN"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        source=ToolSource.MCP,
        plugin_id="demo-plugin",
        timeout_seconds=12,
        side_effects=False,
        idempotent=True,
        result_size_limit=123,
    )
    spec_a = ToolSpec(
        name="a.tool",
        description="First tool",
        input_schema={
            "type": "object",
            "properties": {"payload": {"type": "string"}},
            "required": ["payload"],
            "additionalProperties": False,
        },
        source=ToolSource.LOCAL,
        plugin_id=None,
        timeout_seconds=9,
        side_effects=False,
        idempotent=True,
        result_size_limit=456,
    )

    prompt = build_tool_catalog_prompt([spec_b, spec_a])

    assert prompt.index('"name": "a.tool"') < prompt.index('"name": "b.tool"')
    assert '"kind": "tool_call"' in prompt
    assert '"arguments": {"..."' in prompt
    assert "plugin_id" not in prompt
    assert "source" not in prompt
    assert "timeout_seconds" not in prompt
    assert "result_size_limit" not in prompt
    assert "url_env" not in prompt
    assert "headers_env" not in prompt
    assert "SECRET_TOKEN" not in prompt
    assert "name" in prompt
    assert "description" in prompt
    assert "input_schema" in prompt
    assert "side_effects" in prompt
    assert "idempotent" in prompt


def test_build_tool_catalog_prompt_hides_non_idempotent_side_effect_tools():
    read_spec = ToolSpec(
        name="security.read",
        description="Read security events",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        source=ToolSource.MCP,
        side_effects=False,
        idempotent=True,
    )
    write_spec = ToolSpec(
        name="security.write",
        description="Write a security disposition",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        source=ToolSource.MCP,
        side_effects=True,
        idempotent=False,
    )

    prompt = build_tool_catalog_prompt([read_spec, write_spec])

    assert '"name": "security.read"' in prompt
    assert '"name": "security.write"' not in prompt


def test_build_tool_catalog_prompt_redacts_sensitive_schema_names_and_scalar_values():
    spec = ToolSpec(
        name="demo.secure",
        description="Sensitive schema should be sanitized",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["summary", "detail"],
                },
                "headers_env": {
                    "type": "string",
                    "const": "OPENAI_API_KEY",
                },
                "nested": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["python -m http.server", "safe-choice"],
                        },
                        "callback": {
                            "type": "string",
                            "const": "https://internal.example/api",
                        },
                    },
                    "required": ["command", "callback"],
                    "additionalProperties": False,
                },
            },
            "required": ["query", "headers_env"],
            "additionalProperties": False,
        },
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )

    prompt = build_tool_catalog_prompt([spec])

    assert '"query"' in prompt
    assert '"summary"' in prompt
    assert '"detail"' in prompt
    assert "headers_env" not in prompt
    assert "OPENAI_API_KEY" not in prompt
    assert "python -m http.server" not in prompt
    assert "https://internal.example/api" not in prompt
    assert '"required": [' in prompt
    assert '"query"' in prompt
    assert '[REDACTED]' in prompt
    assert '"command"' in prompt
    assert '"callback"' in prompt


def test_build_tool_catalog_prompt_sanitizes_sensitive_description_content():
    spec = ToolSpec(
        name="demo.description",
        description=(
            "Tool for reading data via https://internal.example/api with "
            "python -m http.server using SECRET_TOKEN and Bearer secret-token"
        ),
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )

    prompt = build_tool_catalog_prompt([spec])

    assert '"description":' in prompt
    assert "Tool for reading data" in prompt
    assert "https://internal.example/api" not in prompt
    assert "python -m http.server" not in prompt
    assert "SECRET_TOKEN" not in prompt
    assert "Bearer secret-token" not in prompt


def test_build_tool_catalog_prompt_redacts_generic_credential_like_description_fragments():
    spec = ToolSpec(
        name="demo.description.generic-creds",
        description="Uses secret-token plus password hunter2 and token abc for auth",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )

    prompt = build_tool_catalog_prompt([spec])

    assert '"description":' in prompt
    assert "Uses " in prompt
    assert "secret-token" not in prompt
    assert "password hunter2" not in prompt
    assert "token abc" not in prompt
    assert prompt.count("[REDACTED]") >= 3


def test_build_tool_catalog_prompt_keeps_safe_required_fields_when_required_precedes_properties():
    spec = ToolSpec(
        name="demo.required-order",
        description="Required field order should not matter",
        input_schema={
            "type": "object",
            "required": ["safe_name", "token_env"],
            "properties": {
                "safe_name": {"type": "string"},
                "token_env": {"type": "string", "const": "OPENAI_API_KEY"},
            },
            "additionalProperties": False,
        },
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )

    prompt = build_tool_catalog_prompt([spec])

    catalog = _catalog_from_prompt(prompt)
    schema = catalog[0]["input_schema"]

    assert schema["properties"] == {"safe_name": {"type": "string"}}
    assert schema["required"] == ["safe_name"]


def test_build_tool_catalog_prompt_sanitizes_nested_additional_properties_schema():
    spec = ToolSpec(
        name="demo.additional-properties",
        description="Nested additionalProperties schema should be sanitized",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": {
                "type": "object",
                "title": "drop-me",
                "properties": {
                    "safe_field": {
                        "type": "string",
                        "enum": ["safe-choice", "Bearer secret-token"],
                    },
                    "headers_env": {
                        "type": "string",
                        "const": "OPENAI_API_KEY",
                    },
                },
                "required": ["safe_field", "headers_env"],
                "additionalProperties": False,
                "default": {"command": "curl https://internal.example/api"},
            },
        },
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )

    prompt = build_tool_catalog_prompt([spec])

    catalog = _catalog_from_prompt(prompt)
    schema = catalog[0]["input_schema"]

    assert schema["additionalProperties"] == {
        "type": "object",
        "properties": {
            "safe_field": {
                "type": "string",
                "enum": ["safe-choice", "[REDACTED]"],
            }
        },
        "required": ["safe_field"],
        "additionalProperties": False,
    }


def test_plan_task_injects_structured_tool_catalog_and_normalizes_items():
    captured = {}

    class RecordingLLM(LLMAdapter):
        def plan(self, prompt: str):
            captured["prompt"] = prompt
            return [
                {"kind": "tool_call", "call_id": "call-1", "tool": "demo.read", "arguments": {"id": "x"}},
                {"tool": "legacy", "payload": "x"},
                "Summarize results",
            ]

    specs = [
        ToolSpec(
            name="demo.read",
            description="Read demo data",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
        )
    ]

    steps = plan_task(
        "Use the demo tool",
        llm=RecordingLLM(),
        structured_tools=True,
        tool_specs=specs,
    )

    assert steps[0].kind == "tool_call"
    assert steps[0].tool == "demo.read"
    assert steps[1] == '{"payload": "x", "tool": "legacy"}'
    assert steps[2] == "Summarize results"
    assert "Tool catalog:" in captured["prompt"]
    assert captured["prompt"].index("Tool catalog:") < captured["prompt"].index("Task:")
    assert '"name": "demo.read"' in captured["prompt"]
    assert '"kind": "tool_call"' in captured["prompt"]


def test_plan_task_structured_mode_coerces_malformed_tool_calls_to_text():
    class RecordingLLM(LLMAdapter):
        def plan(self, prompt: str):
            return [
                {
                    "kind": "tool_call",
                    "call_id": "call-1",
                    "tool": "Demo.Read",
                    "arguments": {},
                }
            ]

    steps = plan_task(
        "Use the demo tool",
        llm=RecordingLLM(),
        structured_tools=True,
        tool_specs=[],
    )

    assert steps == [
        json.dumps(
            {
                "arguments": {},
                "call_id": "call-1",
                "kind": "tool_call",
                "tool": "Demo.Read",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    ]


def test_plan_task_omits_tool_catalog_when_structured_mode_disabled(monkeypatch):
    captured = {}

    monkeypatch.setattr("src.agent.application.planning.service.get_relevant_memory", lambda *args, **kwargs: [])

    class RecordingLLM(LLMAdapter):
        def plan(self, prompt: str):
            captured["prompt"] = prompt
            return [{"kind": "tool_call", "call_id": "call-1", "tool": "demo.read", "arguments": {}}]

    specs = [
        ToolSpec(
            name="demo.read",
            description="Read demo data",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
        )
    ]

    steps = plan_task(
        "Use the demo tool",
        llm=RecordingLLM(),
        structured_tools=False,
        tool_specs=specs,
    )

    assert steps == [{"kind": "tool_call", "call_id": "call-1", "tool": "demo.read", "arguments": {}}]
    assert captured["prompt"] == "Use the demo tool"
