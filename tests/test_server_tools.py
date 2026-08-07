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
