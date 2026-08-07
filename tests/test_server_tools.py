from fastapi.testclient import TestClient
import pytest
from src.agent import server


def test_tools_endpoint():
    client = TestClient(server.app)
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    assert any(tool["name"] == "http_get" for tool in tools)
    assert any(tool["name"] == "http_post" for tool in tools)


def test_tools_endpoint_uses_default_user_when_authentication_is_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "false")
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)

    response = TestClient(server.app).get("/api/tools")

    assert response.status_code == 200


def test_unicode_api_key_is_authenticated_without_server_error(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:秘密")

    from src.agent.auth import get_current_user

    assert get_current_user("秘密") == "alice"


def test_authenticated_api_keys_cannot_reserve_default_owner(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "default:secret")

    from src.agent.auth import get_current_user

    with pytest.raises(Exception) as exc_info:
        get_current_user("secret")

    assert exc_info.value.status_code == 401
