import json
import socket
import requests
import pytest

from src.agent.capabilities.models import ToolCall, ToolInvocationContext
from src.agent.executor import (
    WorkflowExecutionError,
    WorkflowRunner,
    enqueue_task_execution,
    execute_step,
    execute_structured_calls,
    execute_tasks,
    execute_workflow,
)
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


@pytest.mark.anyio
async def test_execute_structured_calls_preserves_order():
    register_tool("test_record_order", lambda payload: payload)
    calls = [
        ToolCall(call_id="1", tool="test_record_order", arguments={"payload": "first"}),
        ToolCall(call_id="2", tool="test_record_order", arguments={"payload": "second"}),
    ]

    results = await execute_structured_calls(calls, ToolInvocationContext())

    assert [result.content for result in results] == ["first", "second"]


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
