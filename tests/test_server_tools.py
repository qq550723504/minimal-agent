from fastapi.testclient import TestClient
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
