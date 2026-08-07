from fastapi.testclient import TestClient
from src.agent import server
from src.agent.task_queue import enqueue_task


def test_handle_endpoint():
    client = TestClient(server.app)
    resp = client.post("/api/handle", json={"prompt": "hello"})
    assert resp.status_code == 200
    assert resp.json()["result"]


def test_api_requires_valid_key_when_authentication_is_enabled(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret,bob:other")
    client = TestClient(server.app)

    assert client.get("/api/tools").status_code == 401
    assert client.get("/api/tools", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/tools", headers={"X-API-Key": "secret"}).status_code == 200


def test_task_status_is_scoped_to_authenticated_owner(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret,bob:other")
    task_id = enqueue_task(lambda: "done", owner_id="alice")
    client = TestClient(server.app)

    assert client.get(f"/api/tasks/{task_id}", headers={"X-API-Key": "other"}).status_code == 404
    assert client.get(f"/api/tasks/{task_id}", headers={"X-API-Key": "secret"}).status_code == 200


def test_invalid_prompt_returns_bad_request(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "false")
    client = TestClient(server.app)

    response = client.post("/api/handle", json={"prompt": "bad\x00input"})

    assert response.status_code == 400


def test_metrics_requires_key_when_authentication_is_enabled(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret")
    client = TestClient(server.app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": "secret"}).status_code == 200
