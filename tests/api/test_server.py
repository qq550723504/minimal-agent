import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.agent.application import requests as main
from src.agent.application.execution.service import ExecutionReport
from src.agent.api import app as server
from src.agent.domain.capabilities.models import (
    ToolCall,
    ToolInvocationContext,
    ToolResult,
    ToolResultStatus,
    ToolSource,
    ToolSpec,
)
from src.agent.domain.planning.models import ToolCallPlan
from src.agent.infrastructure.plugins.catalog import LoadedPlugin, PluginCatalog
from src.agent.infrastructure.plugins.models import PluginManifest
from src.agent.infrastructure.skills.loader import SkillCatalog
from src.agent.infrastructure.workflows.task_queue import enqueue_task
from src.agent.tool_registry import get_capability_registry
from src.agent.infrastructure.mcp.adapter import encode_remote_tool_name
from src.agent.namespaces import capability_namespaced_id


ROOT = Path(__file__).parents[2]


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


def test_structured_handle_endpoint_returns_agent_blocks(monkeypatch):
    seen = []

    async def fake_handle_input_structured_async(prompt, user_id="default", skill_catalog=None):
        seen.append((prompt, user_id, skill_catalog))
        return {
            "message": "机房存在严重消防风险。",
            "blocks": [{"type": "security_event_detail", "data": {"event_id": "event-fire-003"}}],
            "run_id": "run-structured-1",
        }

    monkeypatch.setattr(server, "handle_input_structured_async", fake_handle_input_structured_async)
    client = TestClient(server.app)
    resp = client.post("/api/handle", json={"prompt": "机房有火灾风险吗？", "response_mode": "structured"})

    assert resp.status_code == 200
    assert resp.json()["message"] == "机房存在严重消防风险。"
    assert resp.json()["blocks"][0]["type"] == "security_event_detail"
    assert seen == [("机房有火灾风险吗？", "default", server.app.state.skill_catalog)]


def test_stream_handle_endpoint_returns_sse_events(monkeypatch):
    seen = []

    async def fake_stream_input_structured_async(prompt, user_id="default", skill_catalog=None):
        seen.append((prompt, user_id, skill_catalog))
        yield {"event": "status", "data": {"message": "开始处理"}}
        yield {"event": "result", "data": {"message": "已完成", "blocks": [], "run_id": "run-stream-1"}}

    monkeypatch.setattr(server, "stream_input_structured_async", fake_stream_input_structured_async)
    client = TestClient(server.app)
    resp = client.post(
        "/api/handle/stream",
        json={"prompt": "查询园区安防态势汇总", "response_mode": "stream"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in resp.text
    assert '"message": "开始处理"' in resp.text
    assert "event: result" in resp.text
    assert '"run_id": "run-stream-1"' in resp.text
    assert seen == [("查询园区安防态势汇总", "default", server.app.state.skill_catalog)]


def test_structured_response_blocks_decode_security_tool_and_unwrap_data():
    result = ToolResult(
        call_id="summary-1",
        tool=capability_namespaced_id(
            "park-security", "security", encode_remote_tool_name("security.get_event_summary")
        ),
        status=ToolResultStatus.SUCCESS,
        content={
            "success": True,
            "data": {"park_id": "park-1", "total_events": 3, "risk_counts": {"critical": 1}},
        },
    )

    blocks = main._build_response_blocks([result])

    assert blocks == [{
        "type": "security_summary",
        "tool": "security.get_event_summary",
        "data": {"park_id": "park-1", "total_events": 3, "risk_counts": {"critical": 1}},
    }]


def test_planner_security_tool_typo_is_mapped_to_registered_capability():
    registry = get_capability_registry().__class__()
    canonical = capability_namespaced_id(
        "park-security", "security", encode_remote_tool_name("security.get_shift_context")
    )
    registry.register(
        ToolSpec(
            name=canonical,
            description="shift",
            input_schema={"type": "object"},
            source=ToolSource.MCP,
            plugin_id="park-security",
            side_effects=False,
            idempotent=True,
        ),
        lambda _arguments, _context: {},
    )

    steps = main._normalise_planner_tool_aliases(
        [ToolCallPlan(
            kind="tool_call",
            call_id="shift-1",
            tool="securiy.get_shift_context",
            arguments={"park_id": "park-1"},
        )],
        registry,
    )

    assert steps[0].tool == canonical


@pytest.mark.parametrize(
    ("remote_tool", "block_type", "data"),
    [
        ("energy.query_trend", "energy_trend", {"total": 720.0, "points": []}),
        ("energy.query_ranking", "energy_ranking", {"items": []}),
        ("energy.get_peak_value", "energy_peak", {"value": 42.0}),
        ("energy.compare_period", "energy_compare", {"delta": -3.0}),
        ("energy.get_alarm_summary", "energy_alarm", {"anomalies": []}),
    ],
)
def test_structured_response_blocks_decode_energy_tools(remote_tool, block_type, data):
    result = ToolResult(
        call_id=f"{block_type}-1",
        tool=capability_namespaced_id(
            "park-energy", "energy", encode_remote_tool_name(remote_tool)
        ),
        status=ToolResultStatus.SUCCESS,
        content={"success": True, "data": data},
    )

    blocks = main._build_response_blocks([result])

    assert blocks == [{"type": block_type, "tool": remote_tool, "data": data}]


def test_agent_serves_security_dashboard_from_same_origin():
    client = TestClient(server.app)

    response = client.get("/park-agent/")

    assert response.status_code == 200
    assert "园区智能运营 Agent" in response.text


def test_legacy_security_dashboard_route_remains_available():
    response = TestClient(server.app).get("/security/")

    assert response.status_code == 200
    assert "园区智能运营 Agent" in response.text


def test_agent_dashboard_serves_external_assets():
    client = TestClient(server.app)

    for asset in ("styles.css", "app.js", "mock-data.js"):
        response = client.get(f"/park-agent/{asset}")
        assert response.status_code == 200


@pytest.mark.anyio
async def test_handle_input_structured_async_builds_security_message_and_blocks(monkeypatch):
    registry = get_capability_registry().__class__()
    tool = ToolResult(
        call_id="summary-1",
        tool="security.get_event_summary",
        status=ToolResultStatus.SUCCESS,
        content={"total_events": 3, "risk_counts": {"critical": 1, "high": 2}},
    )

    monkeypatch.setattr(main, "get_capability_registry", lambda: registry)
    monkeypatch.setattr(main, "_structured_tool_calling_enabled", lambda: True)
    monkeypatch.setattr(main, "plan_task", lambda *args, **kwargs: [])

    async def fake_execute_plan_items_detailed(*args, **kwargs):
        return ExecutionReport(results=[], tool_results=[tool])

    monkeypatch.setattr(main, "execute_plan_items_detailed", fake_execute_plan_items_detailed)

    response = await main.handle_input_structured_async("园区当前有多少事件？")

    assert response["message"] == "当前园区有 3 个归并安防事件，其中严重/高风险 3 个。"
    assert response["blocks"][0]["type"] == "security_summary"


@pytest.mark.anyio
async def test_handle_input_async_uses_legacy_separator_when_structured_mode_disabled(monkeypatch):
    registry = get_capability_registry().__class__()
    captured = {}

    monkeypatch.setattr("src.agent.application.requests.STRUCTURED_TOOL_CALLING_ENABLED", False)
    monkeypatch.setattr("src.agent.application.requests.get_capability_registry", lambda: registry)

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

    monkeypatch.setattr("src.agent.application.requests.plan_task", fake_plan_task)
    monkeypatch.setattr("src.agent.application.requests.execute_plan_items", fake_execute_plan_items)

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
    monkeypatch.setattr("src.agent.application.requests.STRUCTURED_TOOL_CALLING_ENABLED", True)
    monkeypatch.setattr(
        "src.agent.application.requests.get_capability_registry",
        lambda: get_capability_registry().__class__(),
    )
    monkeypatch.setattr(
        "src.agent.application.requests.plan_task",
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
        allowed_tools=None,
    ):
        seen["steps"] = steps
        seen["owner_id"] = owner_id
        seen["run_id"] = run_id
        seen["active_skill_ids"] = active_skill_ids
        seen["allowed_tools"] = allowed_tools
        return ["skill-result"]

    monkeypatch.setattr("src.agent.application.requests.execute_plan_items", fake_execute_plan_items)
    server.app.state.skill_catalog = _skill_catalog(tmp_path)

    client = TestClient(server.app)
    response = client.post("/api/handle", json={"prompt": "Please review pull request"})

    assert response.status_code == 200
    assert response.json()["result"] == "skill-result"
    assert seen["owner_id"] == "default"
    assert isinstance(seen["run_id"], str) and seen["run_id"]
    assert seen["active_skill_ids"] == ("demo.review",)
    assert seen["allowed_tools"] == set()


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
