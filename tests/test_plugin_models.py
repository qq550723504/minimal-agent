import pytest
from pydantic import ValidationError

from src.agent.plugins.models import PluginManifest


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_allowed_tool_rejects_non_finite_timeout(timeout):
    with pytest.raises(ValidationError, match="timeout_seconds"):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "mcp_servers": [
                    {
                        "id": "remote",
                        "transport": "streamable_http",
                        "url_env": "DEMO_URL",
                        "allowed_tools": [
                            {
                                "name": "search",
                                "side_effects": False,
                                "idempotent": True,
                                "timeout_seconds": timeout,
                            }
                        ],
                    }
                ],
            }
        )


@pytest.mark.parametrize("field", ["side_effects", "idempotent"])
def test_allowed_tool_requires_strict_booleans(field):
    payload = {
        "api_version": "minimal-agent/v1",
        "id": "demo",
        "version": "1.0.0",
        "mcp_servers": [
            {
                "id": "remote",
                "transport": "streamable_http",
                "url_env": "DEMO_URL",
                "allowed_tools": [
                    {
                        "name": "search",
                        "side_effects": False,
                        "idempotent": True,
                    }
                ],
            }
        ],
    }
    payload["mcp_servers"][0]["allowed_tools"][0][field] = 1

    with pytest.raises(ValidationError):
        PluginManifest.model_validate(payload)


def test_manifest_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "surprise": True,
            }
        )


@pytest.mark.parametrize("required_value", ["true", "yes", 1])
def test_manifest_requires_a_real_boolean_for_required(required_value):
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "required": required_value,
            }
        )


def test_allowed_tool_requires_retry_semantics():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "mcp_servers": [
                    {
                        "id": "remote",
                        "transport": "streamable_http",
                        "url_env": "DEMO_URL",
                        "allowed_tools": [{"name": "search"}],
                    }
                ],
            }
        )


def test_manifest_rejects_duplicate_ids_triggers_and_tool_names():
    with pytest.raises(ValidationError, match="duplicate skill id"):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "skills": [
                    {"id": "one", "path": "skills/one/SKILL.md", "triggers": ["start"]},
                    {"id": "one", "path": "skills/two/SKILL.md", "triggers": ["finish"]},
                ],
            }
        )

    with pytest.raises(ValidationError, match="duplicate skill trigger"):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "skills": [
                    {"id": "one", "path": "skills/one/SKILL.md", "triggers": ["start"]},
                    {"id": "two", "path": "skills/two/SKILL.md", "triggers": ["start"]},
                ],
            }
        )

    with pytest.raises(ValidationError, match="duplicate MCP server id"):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "mcp_servers": [
                    {
                        "id": "remote",
                        "transport": "streamable_http",
                        "url_env": "DEMO_URL",
                        "allowed_tools": [
                            {
                                "name": "search",
                                "side_effects": False,
                                "idempotent": True,
                            }
                        ],
                    },
                    {
                        "id": "remote",
                        "transport": "stdio",
                        "command": "demo-mcp",
                        "allowed_tools": [
                            {
                                "name": "other",
                                "side_effects": False,
                                "idempotent": True,
                            }
                        ],
                    },
                ],
            }
        )

    with pytest.raises(ValidationError, match="duplicate allowed tool name"):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": "1.0.0",
                "mcp_servers": [
                    {
                        "id": "remote",
                        "transport": "streamable_http",
                        "url_env": "DEMO_URL",
                        "allowed_tools": [
                            {
                                "name": "search",
                                "side_effects": False,
                                "idempotent": True,
                            },
                            {
                                "name": "search",
                                "side_effects": False,
                                "idempotent": True,
                            },
                        ],
                    }
                ],
            }
        )


def test_manifest_normalizes_deduplicates_and_ignores_blank_triggers():
    manifest = PluginManifest.model_validate(
        {
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "skills": [
                {
                    "id": "review",
                    "path": "skills/review/SKILL.md",
                    "triggers": ["  Review   PR  ", "review pr", "   "],
                }
            ],
        }
    )

    assert manifest.skills[0].triggers == ["review pr"]


@pytest.mark.parametrize("version", ["", "1", "1.0", "v1.0.0", "1.0.0.0"])
def test_manifest_rejects_non_semantic_versions(version):
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                "api_version": "minimal-agent/v1",
                "id": "demo",
                "version": version,
            }
        )
