import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.agent import main
from src.agent import server
from src.agent.domain.capabilities.models import ToolCall, ToolInvocationContext, ToolSource, ToolSpec
from src.agent.domain.planning.models import ToolCallPlan
from src.agent.plugins.catalog import LoadedPlugin, PluginCatalog
from src.agent.plugins.models import PluginManifest
from src.agent.skills.loader import SkillCatalog
from src.agent.task_queue import enqueue_task
from src.agent.tool_registry import get_capability_registry


ROOT = Path(__file__).parents[1]


def test_handle_endpoint(monkeypatch):
    seen = []

    async def fake_handle_input_async(prompt, user_id="default", skill_catalog=None):
        seen.append((prompt, user_id, skill_catalog))
        return "async-result"

    monkeypatch.setattr(server, "handle_input_async", fake_handle_input_async)
    client = TestClient(server.app)
    resp = client.post("/api/handle", json={"prompt": "hello"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "async-result"
    assert seen == [("hello", "default", server.app.state.skill_catalog)]


@pytest.mark.anyio
async def test_handle_input_async_uses_legacy_separator_when_structured_mode_disabled(monkeypatch):
    registry = get_capability_registry().__class__()
    captured = {}

    monkeypatch.setattr("src.agent.main.STRUCTURED_TOOL_CALLING_ENABLED", False)
    monkeypatch.setattr("src.agent.main.get_capability_registry", lambda: registry)

    def fake_plan_task(prompt, user_id="default", **kwargs):
        captured["structured_tools"] = kwargs["structured_tools"]
        return ["first step", "second step"]

    async def fake_execute_plan_items(
        steps,
        owner_id,
        run_id=None,
        active_skill_ids=(),
        registry=None,
    ):
        return ["alpha", "beta"]

    monkeypatch.setattr("src.agent.main.plan_task", fake_plan_task)
    monkeypatch.setattr("src.agent.main.execute_plan_items", fake_execute_plan_items)

    result = await main.handle_input_async("hello")

    assert captured["structured_tools"] is False
    assert result == "alpha | beta"


def _skill_catalog(root: Path) -> SkillCatalog:
    manifest = PluginManifest.model_validate(
        {
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "skills": [
                {
                    "id": "review",
                    "path": "skills/review/SKILL.md",
                    "triggers": ["review pull request"],
                }
            ],
        }
    )
    skill_path = root / "skills" / "review" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("# review\n", encoding="utf-8")
    catalog = PluginCatalog(
        plugins={
            "demo": LoadedPlugin("demo", root, manifest, {"review": skill_path}),
        }
    )
    return SkillCatalog.from_plugins(catalog)


def test_handle_endpoint_preserves_active_skill_ids_for_async_tool_calls(monkeypatch, tmp_path):
    monkeypatch.setattr("src.agent.main.STRUCTURED_TOOL_CALLING_ENABLED", True)
    monkeypatch.setattr(
        "src.agent.main.get_capability_registry",
        lambda: get_capability_registry().__class__(),
    )
    monkeypatch.setattr(
        "src.agent.main.plan_task",
        lambda prompt, user_id="default", **kwargs: [
            ToolCallPlan(
                kind="tool_call",
                call_id="call-1",
                tool="internal.skill_read_reference",
                arguments={"skill_id": "demo.review", "path": "guide.md"},
            )
        ],
    )

    seen = {}

    async def fake_execute_plan_items(
        steps,
        owner_id,
        run_id=None,
        active_skill_ids=(),
        registry=None,
    ):
        seen["steps"] = steps
        seen["owner_id"] = owner_id
        seen["run_id"] = run_id
        seen["active_skill_ids"] = active_skill_ids
        return ["skill-result"]

    monkeypatch.setattr("src.agent.main.execute_plan_items", fake_execute_plan_items)
    server.app.state.skill_catalog = _skill_catalog(tmp_path)

    client = TestClient(server.app)
    response = client.post("/api/handle", json={"prompt": "Please review pull request"})

    assert response.status_code == 200
    assert response.json()["result"] == "skill-result"
    assert seen["owner_id"] == "default"
    assert isinstance(seen["run_id"], str) and seen["run_id"]
    assert seen["active_skill_ids"] == ("demo.review",)


def test_runtime_and_development_requirements_are_separated():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "pytest" not in runtime
    assert "scikit-learn" not in runtime
    assert "-r requirements.txt" in development
    assert "pytest==9.1.1" in development


def test_fastapi_version_comes_from_service_version_module():
    from src.agent.version import __version__

    assert __version__ == "0.1.0"
    assert server.app.version == __version__


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


def test_mcp_and_tool_metrics_use_only_bounded_non_sensitive_labels(monkeypatch):
    """Metrics must expose runtime outcomes without call IDs or tool arguments."""
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "false")
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    call_id = "metric-call-id"
    secret_argument = "metric-secret-argument"

    with TestClient(server.app) as client:
        asyncio.run(
            get_capability_registry().invoke(
                ToolCall(
                    call_id=call_id,
                    tool="missing.metric.tool",
                    arguments={"secret": secret_argument},
                ),
                ToolInvocationContext(owner_id="sensitive-owner"),
            )
        )
        metrics = client.get("/metrics").text

    assert "agent_plugin_load_total" in metrics
    assert "agent_mcp_connection_status" in metrics
    assert "agent_tool_calls_total" in metrics
    assert "agent_tool_call_duration_seconds" in metrics
    assert "agent_tool_unknown_outcome_total" in metrics
    assert call_id not in metrics
    assert secret_argument not in metrics
    assert "sensitive-owner" not in metrics


def test_shutdown_queue_failure_still_cleans_mcp_runtime_and_memory(monkeypatch):
    """Fails if a queue shutdown error skips later lifecycle cleanup steps."""
    class RecordingManager:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

        def server_ids(self):
            return []

    manager = RecordingManager()
    saved = []

    def fail_stop_queue():
        raise RuntimeError("queue_stop_failure")

    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    monkeypatch.setattr(server.config, "CAPABILITY_RUNTIME_ENABLED", False)
    monkeypatch.setattr(server, "MCPClientManager", lambda: manager)
    monkeypatch.setattr(server, "start_queue", lambda: None)
    monkeypatch.setattr(server, "stop_queue", fail_stop_queue)
    monkeypatch.setattr(server, "save_memory", lambda: saved.append(True))

    registry = get_capability_registry()
    with pytest.raises(ExceptionGroup, match="lifespan_cleanup_failed"):
        with TestClient(server.app):
            registry.register(
                ToolSpec(
                    name="test.shutdown.cleanup",
                    input_schema={"type": "object"},
                    source=ToolSource.MCP,
                    side_effects=False,
                    idempotent=True,
                ),
                lambda _arguments, _context: None,
                replace=True,
            )

    assert manager.closed is True
    assert registry.get_spec("test.shutdown.cleanup") is None
    assert server.app.state.plugin_catalog.plugins == {}
    assert server.app.state.skill_catalog.sorted() == []
    assert server.app.state.mcp_manager is None
    assert saved == [True]


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

    async def fail(*args, **kwargs):
        raise ValueError("provider failure")

    monkeypatch.setattr(server, "handle_input_async", fail)
    client = TestClient(server.app, raise_server_exceptions=False)

    response = client.post("/api/handle", json={"prompt": "hello"})

    assert response.status_code == 500
    assert "provider failure" not in response.text
