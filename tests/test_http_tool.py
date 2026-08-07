import json
import socket

import pytest

from src.agent.tools import _http_get_tool, _http_post_tool
from src.agent.http_security import ParsedURL, pin_dns_resolution, validate_http_url


class FakeResponse:
    def __init__(self, body=b'{"ok": true}', status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {"Content-Length": str(len(body))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_content(self, chunk_size=8192):
        yield self.body


def allow_example_host(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def test_http_get_tool_payload_parsing(monkeypatch):
    allow_example_host(monkeypatch)
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params, kwargs))
        return FakeResponse(body=json.dumps({"url": url, "params": params}).encode())

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    payload = '{"url": "https://api.example.com/data", "params": {"q": "test"}}'
    result = _http_get_tool(payload)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/data"
    assert parsed["params"] == {"q": "test"}
    assert calls[0][2]["allow_redirects"] is False
    assert calls[0][2]["stream"] is True


def test_http_post_tool_payload_parsing(monkeypatch):
    allow_example_host(monkeypatch)

    def fake_post(url, data=None, json=None, **kwargs):
        body = {"url": url, "data": data, "json": json}
        return FakeResponse(body=__import__("json").dumps(body).encode())

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    payload = '{"url": "https://api.example.com/items", "json": {"name": "agent"}}'
    result = _http_post_tool(payload)
    parsed = json.loads(result)
    assert parsed["url"] == "https://api.example.com/items"
    assert parsed["json"] == {"name": "agent"}


def test_http_tool_rejects_empty_allowlist_without_calling_requests(monkeypatch):
    monkeypatch.delenv("AGENT_HTTP_ALLOWED_HOSTS", raising=False)
    called = False

    def fake_get(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(ValueError, match="allowlist"):
        _http_get_tool("https://api.example.com/data")
    assert called is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1:8080/", "http://169.254.169.254/latest"])
def test_http_tool_rejects_unsafe_urls(monkeypatch, url):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "api.example.com")
    called = False

    def fake_get(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(ValueError):
        _http_get_tool(url)
    assert called is False


def test_validate_http_url_rejects_dns_resolving_to_metadata_ip(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "metadata.example.com")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))],
    )

    with pytest.raises(ValueError, match="unsafe"):
        validate_http_url("http://metadata.example.com/latest")


def test_http_tool_rejects_redirect(monkeypatch):
    allow_example_host(monkeypatch)
    import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse(status_code=302))

    with pytest.raises(ValueError, match="redirect"):
        _http_get_tool("https://api.example.com/data")


def test_http_tool_rejects_oversized_response(monkeypatch):
    allow_example_host(monkeypatch)
    monkeypatch.setenv("AGENT_HTTP_MAX_RESPONSE_BYTES", "4")
    import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse(body=b"12345"))

    with pytest.raises(ValueError, match="large"):
        _http_get_tool("https://api.example.com/data")


def test_http_tool_pins_requests_dns_to_the_validated_address(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "api.example.com")
    answers = iter([
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))],
    ])
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: next(answers))

    parsed = validate_http_url("https://api.example.com/data")
    with pin_dns_resolution(parsed):
        pinned = socket.getaddrinfo("api.example.com", 443, type=socket.SOCK_STREAM)

    assert pinned[0][4][0] == "93.184.216.34"


def test_validate_http_url_accepts_unicode_host_against_idna_allowlist(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "xn--bcher-kva.example")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    parsed = validate_http_url("https://bücher.example/data")

    assert parsed.hostname == "bücher.example"


def test_pinned_dns_matches_idna_connection_hostname(monkeypatch):
    parsed = ParsedURL(
        url="https://bücher.example/data",
        scheme="https",
        hostname="bücher.example",
        port=443,
        resolved_addresses=("93.184.216.34",),
    )

    def unexpected_resolution(*args, **kwargs):
        raise AssertionError("validated hostname was not used")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_resolution)
    with pin_dns_resolution(parsed):
        pinned = socket.getaddrinfo("xn--bcher-kva.example", 443, type=socket.SOCK_STREAM)

    assert pinned[0][4][0] == "93.184.216.34"
    assert socket.getaddrinfo is unexpected_resolution
