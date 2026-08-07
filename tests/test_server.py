from fastapi.testclient import TestClient
from src.agent import server


def test_handle_endpoint():
    client = TestClient(server.app)
    resp = client.post("/api/handle", json={"prompt": "hello"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "hello"
