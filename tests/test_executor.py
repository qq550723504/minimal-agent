import json
import requests

from src.agent.executor import execute_step, execute_tasks


def test_execute_step_echo():
    assert execute_step("echo: hello") == "hello"


def test_execute_step_plain_text():
    assert execute_step("just a step") == "just a step"


def test_execute_step_http_get_payload_parsing(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        class FakeResp:
            def __init__(self):
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"url": url, "params": params}

        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    step = "http_get: {\"url\": \"https://api.example.com/data\", \"params\": {\"q\": \"test\"}}"
    result = execute_step(step)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}


def test_execute_step_structured_tool_step(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        class FakeResp:
            def __init__(self):
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"url": url, "params": params}

        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    step = {"tool": "http_get", "payload": {"url": "https://api.example.com/data", "params": {"q": "test"}}}
    result = execute_step(step)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}


def test_execute_tasks_batch():
    assert execute_tasks(["echo: a", "b"]) == ["a", "b"]
