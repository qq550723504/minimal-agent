import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from src.agent.api import app as server
from src.agent.infrastructure.plugins.loader import RequiredPluginError
from src.agent.tool_registry import get_capability_registry


MCP_FIXTURE = Path(__file__).parents[1] / "fixtures" / "mcp_echo_server.py"


def _write_plugin(root: Path) -> None:
    skill = root / "demo" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# private instructions\n", encoding="utf-8")
    (skill.parent / "references").mkdir()
    (skill.parent / "references" / "secret.md").write_text("private reference", encoding="utf-8")
    (root / "demo" / "plugin.yaml").write_text(
        f"""api_version: minimal-agent/v1
id: demo
version: 1.2.3
skills:
  - id: review
    path: skills/review/SKILL.md
    triggers: [review pull request]
mcp_servers:
  - id: local
    transport: stdio
    command: {sys.executable}
    args: [{MCP_FIXTURE.as_posix()}]
    env_vars:
      TOKEN: PLUGIN_TEST_TOKEN
    allowed_tools:
      - name: echo
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )


def _configure_runtime(monkeypatch, plugin_dir: Path, *, enabled: bool) -> None:
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    monkeypatch.setenv("PLUGIN_TEST_TOKEN", "private-token")
    monkeypatch.setattr(server.config, "CAPABILITY_RUNTIME_ENABLED", enabled)
    monkeypatch.setattr(server.config, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(server.config, "MCP_STDIO_ALLOWED_COMMANDS", frozenset({sys.executable}))


def _write_missing_mcp_plugin(root: Path, *, required: bool) -> None:
    plugin = root / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"""api_version: minimal-agent/v1
id: demo
version: 1.0.0
required: {str(required).lower()}
mcp_servers:
  - id: echo
    transport: stdio
    command: {sys.executable}
    args: [{MCP_FIXTURE.as_posix()}]
    allowed_tools:
      - name: missing
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )


def test_plugin_and_skill_catalogs_require_auth(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret")
    _configure_runtime(monkeypatch, Path("does-not-matter"), enabled=False)

    client = TestClient(server.app)
    assert client.get("/api/plugins").status_code == 401
    assert client.get("/api/skills").status_code == 401
    assert client.get("/api/plugins", headers={"X-API-Key": "secret"}).status_code == 200


def test_catalog_endpoints_expose_only_safe_declarations(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_plugin(plugin_dir)
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)

    with TestClient(server.app) as client:
        plugins = client.get("/api/plugins").json()
        skills = client.get("/api/skills").json()

    assert plugins == [
        {
            "installation_name": "demo",
            "state": "enabled",
            "plugin_id": "demo",
            "version": "1.2.3",
            "error_code": None,
            "capabilities": ["echo"],
        }
    ]
    assert skills == [
        {
            "id": "demo.review",
            "plugin_id": "demo",
            "triggers": ["review pull request"],
        }
    ]
    response_text = repr([plugins, skills])
    assert "private-token" not in response_text
    assert "private-command" not in response_text
    assert "private instructions" not in response_text
    assert "private reference" not in response_text


def test_runtime_shutdown_cleans_reference_tool_before_disabled_restart(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_plugin(plugin_dir)
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)

    with TestClient(server.app):
        assert get_capability_registry().get_spec("internal.skill_read_reference") is not None

    _configure_runtime(monkeypatch, tmp_path / "unused", enabled=False)
    with TestClient(server.app) as client:
        assert get_capability_registry().get_spec("internal.skill_read_reference") is None
        assert "internal.skill_read_reference" not in {
            tool["name"] for tool in client.get("/api/tools").json()
        }


def test_enabled_runtime_can_restart_with_the_production_registry(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_plugin(plugin_dir)
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)

    with TestClient(server.app):
        assert get_capability_registry().get_spec("internal.skill_read_reference") is not None
    with TestClient(server.app):
        assert get_capability_registry().get_spec("internal.skill_read_reference") is not None


def test_disabled_runtime_uses_empty_catalogs_without_touching_plugin_directory(monkeypatch, tmp_path):
    absent_plugin_dir = tmp_path / "does-not-exist"
    _configure_runtime(monkeypatch, absent_plugin_dir, enabled=False)

    with TestClient(server.app) as client:
        assert client.get("/api/plugins").json() == []
        assert client.get("/api/skills").json() == []

    assert not absent_plugin_dir.exists()


def test_required_plugin_load_error_propagates_from_startup(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin = plugin_dir / "required"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: required
version: 1.0.0
required: true
skills:
  - id: missing
    path: skills/missing/SKILL.md
""",
        encoding="utf-8",
    )
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)

    with pytest.raises(RequiredPluginError, match="plugin_skill_missing"):
        with TestClient(server.app):
            pass


def test_optional_mcp_plugin_failure_leaves_api_healthy_and_reports_safe_status(
    monkeypatch, tmp_path
):
    """Fails if lifespan stops treating optional MCP discovery errors as catalog state."""
    plugin_dir = tmp_path / "plugins"
    _write_missing_mcp_plugin(plugin_dir, required=False)
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)
    monkeypatch.setattr(server.config, "MCP_STDIO_ALLOWED_COMMANDS", frozenset({sys.executable}))

    with TestClient(server.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/plugins").json() == [
            {
                "installation_name": "demo",
                "state": "disabled",
                "plugin_id": "demo",
                "version": "1.0.0",
                "error_code": "declared_tool_missing",
                "capabilities": [],
            }
        ]


def test_required_mcp_plugin_failure_prevents_application_startup(monkeypatch, tmp_path):
    """Fails if required MCP discovery errors no longer abort TestClient startup."""
    plugin_dir = tmp_path / "plugins"
    _write_missing_mcp_plugin(plugin_dir, required=True)
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)
    monkeypatch.setattr(server.config, "MCP_STDIO_ALLOWED_COMMANDS", frozenset({sys.executable}))

    with pytest.raises(RequiredPluginError, match="declared_tool_missing"):
        with TestClient(server.app):
            pass


def test_handle_endpoint_invokes_capability_registry_for_structured_mcp_calls(
    monkeypatch, tmp_path
):
    plugin_dir = tmp_path / "plugins"
    plugin = plugin_dir / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"""api_version: minimal-agent/v1
id: demo
version: 1.0.0
mcp_servers:
  - id: local
    transport: stdio
    command: {sys.executable}
    args: [{MCP_FIXTURE.as_posix()}]
    allowed_tools:
      - name: park_energy
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )
    _configure_runtime(monkeypatch, plugin_dir, enabled=True)
    monkeypatch.setattr(server.config, "STRUCTURED_TOOL_CALLING_ENABLED", True)

    class FakeStructuredLLM:
        def plan(self, _prompt):
            return [
                {
                    "kind": "tool_call",
                    "call_id": "park-energy-api",
                    "tool": "demo.local.park_energy",
                    "arguments": {"park_id": "north-campus"},
                }
            ]

    monkeypatch.setattr("src.agent.application.planning.service.create_llm_adapter", lambda: FakeStructuredLLM())
    registry = get_capability_registry()
    seen = []
    original_invoke = registry.invoke

    async def recording_invoke(call, context):
        seen.append((call.tool, call.arguments, context.owner_id))
        return await original_invoke(call, context)

    monkeypatch.setattr(registry, "invoke", recording_invoke)

    with TestClient(server.app) as client:
        response = client.post("/api/handle", json={"prompt": "Read park energy"})

    assert response.status_code == 200
    assert json.loads(response.json()["result"]) == {
        "average_kw": 12.5,
        "park_id": "north-campus",
        "peak_kw": 18.0,
        "window_hours": 24,
    }
    assert seen == [
        ("demo.local.park_energy", {"park_id": "north-campus"}, "default")
    ]
