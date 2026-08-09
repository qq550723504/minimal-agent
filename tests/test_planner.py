from src.agent.capabilities.models import ToolSource, ToolSpec
from src.agent.memory import get_global_memory
from src.agent.planner import build_tool_catalog_prompt, plan_task, _build_rag_prompt
from src.agent.llm import MockLLM, LLMAdapter


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


def test_plan_task_skips_default_user_history():
    class RecordingLLM(LLMAdapter):
        def __init__(self):
            self.prompt = None

        def plan(self, prompt: str):
            self.prompt = prompt
            return [prompt]

    llm = RecordingLLM()
    mem = get_global_memory()
    mem.add("default", {"prompt": "Earlier request about deployment."})

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

    monkeypatch.setattr("src.agent.planner.get_relevant_memory", fake_relevant_memory)
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
        side_effects=True,
        idempotent=False,
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


def test_plan_task_omits_tool_catalog_when_structured_mode_disabled(monkeypatch):
    captured = {}

    monkeypatch.setattr("src.agent.planner.get_relevant_memory", lambda *args, **kwargs: [])

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
