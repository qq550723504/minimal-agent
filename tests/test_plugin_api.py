from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent import server
from src.agent.capabilities.registry import CapabilityRegistry
from src.agent.plugins.loader import RequiredPluginError


def _write_plugin(root: Path) -> None:
    skill = root / "demo" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# private instructions\n", encoding="utf-8")
    (skill.parent / "references").mkdir()
    (skill.parent / "references" / "secret.md").write_text("private reference", encoding="utf-8")
    (root / "demo" / "plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: demo
version: 1.2.3
skills:
  - id: review
    path: skills/review/SKILL.md
    triggers: [review pull request]
mcp_servers:
  - id: local
    transport: stdio
    command: private-command
    env_vars:
      TOKEN: private-token
    allowed_tools:
      - name: read_issue
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )


def _configure_runtime(monkeypatch, plugin_dir: Path, *, enabled: bool) -> None:
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    monkeypatch.setattr(server.config, "CAPABILITY_RUNTIME_ENABLED", enabled)
    monkeypatch.setattr(server.config, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(server, "get_capability_registry", CapabilityRegistry)


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
            "capabilities": ["read_issue"],
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
