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
    monkeypatch.setenv("AGENT_METRICS_API_KEY", "secret")
    client = TestClient(server.app)

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_generated_api_docs_require_authentication(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret")
    client = TestClient(server.app)

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert TestClient(server.app).get(path).status_code == 401
        assert client.get(path, headers={"X-API-Key": "secret"}).status_code == 200


def test_authenticated_docs_session_can_fetch_openapi_without_header(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret")
    client = TestClient(server.app)

    response = client.get("/docs", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    assert response.cookies.get("agent_session") == "secret"
    assert client.get("/openapi.json").status_code == 200

    redoc_response = client.get("/redoc", headers={"X-API-Key": "secret"})
    assert redoc_response.status_code == 200
    assert redoc_response.cookies.get("agent_session") == "secret"


def test_downstream_value_error_is_not_reported_as_client_input(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "false")

    def fail(*args, **kwargs):
        raise ValueError("provider failure")

    monkeypatch.setattr(server, "handle_input", fail)
    client = TestClient(server.app, raise_server_exceptions=False)

    response = client.post("/api/handle", json={"prompt": "hello"})

    assert response.status_code == 500
    assert "provider failure" not in response.text
