import json
import socket
import requests
import pytest

from src.agent.capabilities.errors import ToolExecutionError
from src.agent.capabilities.models import ToolSource, ToolSpec
from src.agent.capabilities.registry import CapabilityRegistry
from src.agent.capabilities.models import ToolCall, ToolInvocationContext
from src.agent.config import MAX_TOOL_RESULT_BYTES
from src.agent.executor import (
    WorkflowExecutionError,
    WorkflowRunner,
    enqueue_task_execution,
    execute_plan_items,
    execute_step,
    execute_structured_calls,
    execute_tasks,
    execute_workflow,
)
from src.agent.plan_models import ToolCallPlan
from src.agent.tool_registry import register_tool


def _patch_http_session(monkeypatch, request_fn):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def request(self, method, url, **kwargs):
            return request_fn(url, **kwargs)

    monkeypatch.setattr(requests, "Session", FakeSession)


def test_execute_step_echo():
    assert execute_step("echo: hello") == "hello"


def test_execute_step_plain_text():
    assert execute_step("just a step") == "just a step"


def test_execute_step_http_get_payload_parsing(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def fake_get(url, params=None, **kwargs):
        class FakeResp:
            def __init__(self):
                self.status_code = 200
                self.headers = {"Content-Length": "50"}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=8192):
                yield json.dumps({"url": url, "params": params}).encode()

            def close(self):
                pass

        return FakeResp()

    _patch_http_session(monkeypatch, fake_get)
    step = "http_get: {\"url\": \"https://api.example.com/data\", \"params\": {\"q\": \"test\"}}"
    result = execute_step(step)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}


def test_execute_step_structured_tool_step(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def fake_get(url, params=None, **kwargs):
        class FakeResp:
            def __init__(self):
                self.status_code = 200
                self.headers = {"Content-Length": "50"}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=8192):
                yield json.dumps({"url": url, "params": params}).encode()

            def close(self):
                pass

        return FakeResp()

    _patch_http_session(monkeypatch, fake_get)
    step = {"tool": "http_get", "payload": {"url": "https://api.example.com/data", "params": {"q": "test"}}}
    result = execute_step(step)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}


def test_execute_tasks_batch():
    assert execute_tasks(["echo: a", "b"]) == ["a", "b"]


def _make_capability_spec(name: str, **overrides) -> ToolSpec:
    values = {
        "name": name,
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "source": ToolSource.LOCAL,
        "side_effects": False,
        "idempotent": True,
    }
    values.update(overrides)
    return ToolSpec(**values)


@pytest.mark.anyio
async def test_execute_structured_calls_preserves_order():
    register_tool("test_record_order", lambda payload: payload)
    calls = [
        ToolCall(call_id="1", tool="test_record_order", arguments={"payload": "first"}),
        ToolCall(call_id="2", tool="test_record_order", arguments={"payload": "second"}),
    ]

    results = await execute_structured_calls(calls, ToolInvocationContext())

    assert [result.content for result in results] == ["first", "second"]


@pytest.mark.anyio
async def test_execute_plan_items_runs_text_and_tool_call_in_order():
    seen = []
    registry = CapabilityRegistry()

    async def handler(arguments, context):
        seen.append((arguments, context.owner_id, context.run_id))
        return {"value": arguments["value"]}

    registry.register(_make_capability_spec("test.echo"), handler)

    result = await execute_plan_items(
        [
            "first",
            ToolCallPlan(
                kind="tool_call",
                call_id="call-1",
                tool="test.echo",
                arguments={"value": "second"},
            ),
        ],
        owner_id="user-1",
        run_id="run-1",
        registry=registry,
    )

    assert result[0] == "first"
    assert '"value": "second"' in result[1]
    assert seen == [({"value": "second"}, "user-1", "run-1")]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("call", "spec", "handler", "expected"),
    [
        (
            ToolCallPlan(kind="tool_call", call_id="call-1", tool="demo.missing", arguments={"value": "x"}),
            None,
            None,
            {"status": "error", "error_code": "unknown_tool", "retryable": False},
        ),
        (
            ToolCallPlan(kind="tool_call", call_id="call-2", tool="demo.invalid", arguments={"value": 1}),
            _make_capability_spec("demo.invalid"),
            lambda arguments, context: arguments["value"],
            {"status": "error", "error_code": "invalid_tool_arguments", "retryable": False},
        ),
        (
            ToolCallPlan(kind="tool_call", call_id="call-3", tool="demo.unknown", arguments={"value": "x"}),
            _make_capability_spec("demo.unknown"),
            lambda arguments, context: (_ for _ in ()).throw(
                ToolExecutionError("remote_state_unknown", unknown_outcome=True)
            ),
            {"status": "unknown_outcome", "error_code": "remote_state_unknown", "retryable": False},
        ),
        (
            ToolCallPlan(kind="tool_call", call_id="call-4", tool="demo.large", arguments={"value": "x"}),
            _make_capability_spec("demo.large", result_size_limit=3),
            lambda arguments, context: "four",
            {"status": "error", "error_code": "tool_result_too_large", "retryable": False},
        ),
    ],
)
async def test_execute_plan_items_renders_stable_tool_result_status(call, spec, handler, expected):
    registry = CapabilityRegistry()
    if spec is not None:
        registry.register(spec, handler)

    result = await execute_plan_items([call], owner_id="user-1", registry=registry)

    assert json.loads(result[0]) == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    [
        pytest.param("x" * (MAX_TOOL_RESULT_BYTES + 1), id="string"),
        pytest.param({"value": "x" * (MAX_TOOL_RESULT_BYTES + 1)}, id="object"),
    ],
)
async def test_execute_plan_items_returns_stable_error_when_rendered_success_exceeds_global_limit(content):
    registry = CapabilityRegistry(max_result_bytes=MAX_TOOL_RESULT_BYTES + 4096)
    registry.register(
        _make_capability_spec(
            "demo.large_render",
            result_size_limit=MAX_TOOL_RESULT_BYTES + 4096,
        ),
        lambda arguments, context: content,
    )

    result = await execute_plan_items(
        [
            ToolCallPlan(
                kind="tool_call",
                call_id="call-large-render",
                tool="demo.large_render",
                arguments={"value": "ok"},
            )
        ],
        owner_id="user-1",
        registry=registry,
    )

    assert json.loads(result[0]) == {
        "status": "error",
        "error_code": "tool_result_too_large",
        "retryable": False,
    }


def test_execute_workflow_preserves_step_order():
    events = []

    def record(payload):
        events.append(payload)
        return payload

    register_tool("test_record_order", record)

    result = execute_workflow(["test_record_order: first", "test_record_order: second"])

    assert result == ["first", "second"]
    assert events == ["first", "second"]


def test_execute_workflow_reports_failed_step():
    def fail(_payload):
        raise RuntimeError("boom")

    register_tool("test_workflow_failure", fail)

    try:
        execute_workflow(["echo: first", "test_workflow_failure: second"])
    except WorkflowExecutionError as exc:
        assert exc.step_index == 1
        assert "boom" in str(exc)
    else:
        raise AssertionError("execute_workflow should report the failed step")


def test_enqueue_task_execution_creates_one_workflow_task(monkeypatch):
    calls = []

    def fake_enqueue(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return "workflow-task"

    monkeypatch.setattr("src.agent.executor.enqueue_task", fake_enqueue)
    monkeypatch.setattr("src.agent.executor.get_workflow_store", lambda: None)

    result = enqueue_task_execution(["echo: first", "echo: second"], owner_id="alice")

    assert result == {"status": "queued", "task_id": "workflow-task", "task_ids": ["workflow-task"]}
    assert len(calls) == 1
    assert calls[0][0].__name__ == "execute_workflow"
    assert calls[0][1] == ()
    assert isinstance(calls[0][0], WorkflowRunner)
    assert calls[0][0].steps == ["echo: first", "echo: second"]
    assert calls[0][2]["owner_id"] == "alice"
