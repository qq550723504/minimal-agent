import json

from src.agent.tools import _http_get_tool, _http_post_tool


def test_http_get_tool_payload_parsing(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        class FakeResp:
            def __init__(self):
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"url": url, "params": params}

        return FakeResp()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    payload = '{"url": "https://api.example.com/data", "params": {"q": "test"}}'
    result = _http_get_tool(payload)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}


def test_http_post_tool_payload_parsing(monkeypatch):
    def fake_post(url, data=None, json=None, timeout=None):
        class FakeResp:
            def __init__(self):
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"url": url, "data": data, "json": json}

        return FakeResp()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    payload = '{"url": "https://api.example.com/items", "json": {"name": "agent"}}'
    result = _http_post_tool(payload)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/items"
    assert parsed["json"] == {"name": "agent"}
