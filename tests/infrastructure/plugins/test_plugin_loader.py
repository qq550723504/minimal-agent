from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from src.agent.infrastructure.plugins.loader import PluginLoader, RequiredPluginError


def write_plugin(
    root: Path,
    directory: str,
    *,
    plugin_id: str | None = None,
    required: bool = False,
    skill_path: str = "skills/demo/SKILL.md",
    skill_contents: bytes = b"# Demo\n",
) -> Path:
    plugin = root / directory
    skill = plugin / skill_path
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_bytes(skill_contents)
    plugin.joinpath("plugin.yaml").write_text(
        "\n".join(
            [
                "api_version: minimal-agent/v1",
                f"id: {plugin_id or directory}",
                "version: 1.0.0",
                f"required: {str(required).lower()}",
                "skills:",
                "  - id: demo",
                f"    path: {skill_path}",
            ]
        ),
        encoding="utf-8",
    )
    return plugin


def test_loader_rejects_skill_path_outside_plugin(tmp_path):
    plugin = tmp_path / "plugins" / "demo"
    plugin.mkdir(parents=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (plugin / "plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: demo
version: 1.0.0
skills:
  - id: bad
    path: ../../outside.md
""",
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path / "plugins").load_all()

    assert catalog.statuses["demo"].state == "disabled"
    assert catalog.statuses["demo"].error_code == "plugin_path_escape"


def test_required_plugin_error_stops_loading(tmp_path):
    plugin = write_plugin(tmp_path, "required", required=True, skill_path="missing/SKILL.md")
    plugin.joinpath("missing/SKILL.md").unlink()

    with pytest.raises(RequiredPluginError) as error:
        PluginLoader(tmp_path).load_all()

    assert error.value.error_code == "plugin_skill_missing"


def test_duplicate_plugin_id_disables_second_plugin(tmp_path):
    write_plugin(tmp_path, "one", plugin_id="same")
    write_plugin(tmp_path, "two", plugin_id="same")

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["one"].state == "enabled"
    assert catalog.statuses["two"].error_code == "duplicate_plugin_id"
    assert list(catalog.plugins) == ["same"]


def test_duplicate_disabled_plugin_id_disables_later_enabled_plugin(tmp_path):
    first = write_plugin(tmp_path, "one", plugin_id="same")
    first.joinpath("plugin.yaml").write_text(
        first.joinpath("plugin.yaml").read_text(encoding="utf-8").replace(
            "required: false", "enabled: false\nrequired: false"
        ),
        encoding="utf-8",
    )
    write_plugin(tmp_path, "two", plugin_id="same")

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["one"].state == "disabled"
    assert catalog.statuses["two"].error_code == "duplicate_plugin_id"
    assert catalog.plugins == {}


@pytest.mark.parametrize("required_value", ['"true"', '"yes"', "1"])
def test_loader_rejects_coerced_required_values(tmp_path, required_value):
    plugin = tmp_path / "required"
    plugin.mkdir()
    plugin.joinpath("plugin.yaml").write_text(
        f"""api_version: minimal-agent/v1
id: required
version: 1.0.0
required: {required_value}
skills:
  - id: demo
    path: missing/SKILL.md
""",
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["required"].error_code == "plugin_manifest_invalid"


def test_loader_reports_malformed_yaml_without_parser_details(tmp_path):
    plugin = tmp_path / "broken"
    plugin.mkdir()
    plugin.joinpath("plugin.yaml").write_text("id: [unterminated", encoding="utf-8")

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["broken"].error_code == "plugin_manifest_invalid"


def test_loader_reports_manifest_validation_errors_with_a_stable_code(tmp_path):
    plugin = tmp_path / "broken"
    plugin.mkdir()
    plugin.joinpath("plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: broken
version: 1.0.0
unexpected: true
""",
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["broken"].error_code == "plugin_manifest_invalid"


def test_required_invalid_manifest_raises_a_sanitized_error(tmp_path):
    plugin = tmp_path / "required"
    plugin.mkdir()
    plugin.joinpath("plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: required
version: 1.0.0
required: true
unexpected: true
""",
        encoding="utf-8",
    )

    with pytest.raises(RequiredPluginError) as error:
        PluginLoader(tmp_path).load_all()

    assert error.value.error_code == "plugin_manifest_invalid"


def test_loader_rejects_symlink_or_junction_skill_directory(tmp_path):
    plugin = tmp_path / "demo"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("SKILL.md").write_text("# outside", encoding="utf-8")
    plugin.mkdir()
    try:
        os.symlink(outside, plugin / "skills", target_is_directory=True)
    except OSError as error:
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(plugin / "skills"), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode:
            pytest.skip(f"symlink and junction creation unavailable: {error}")
    plugin.joinpath("plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: demo
version: 1.0.0
skills:
  - id: demo
    path: skills/SKILL.md
""",
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["demo"].error_code == "plugin_path_escape"


def test_loader_rejects_junction_plugin_installation_before_reading_manifest(tmp_path):
    plugin_root = tmp_path / "plugins"
    outside = tmp_path / "outside"
    plugin_root.mkdir()
    outside.mkdir()
    outside.joinpath("plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: escaped
version: 1.0.0
""",
        encoding="utf-8",
    )
    installation = plugin_root / "escaped-install"
    try:
        os.symlink(outside, installation, target_is_directory=True)
    except OSError as error:
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(installation), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode:
            pytest.skip(f"symlink and junction creation unavailable: {error}")

    catalog = PluginLoader(plugin_root).load_all()

    assert catalog.plugins == {}
    assert catalog.statuses["escaped-install"].error_code == "plugin_path_escape"


def test_loader_rejects_non_utf8_skill_file(tmp_path):
    write_plugin(tmp_path, "demo", skill_contents=b"\xff\xfe")

    catalog = PluginLoader(tmp_path).load_all()

    assert catalog.statuses["demo"].error_code == "plugin_skill_not_utf8"


def test_loader_sorts_installation_directories_and_keeps_disabled_plugins_visible(tmp_path):
    write_plugin(tmp_path, "zulu")
    alpha = write_plugin(tmp_path, "alpha")
    alpha.joinpath("plugin.yaml").write_text(
        alpha.joinpath("plugin.yaml").read_text(encoding="utf-8").replace(
            "required: false", "enabled: false\nrequired: false"
        ),
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path).load_all()

    assert list(catalog.statuses) == ["alpha", "zulu"]
    assert catalog.statuses["alpha"].state == "disabled"
    assert catalog.statuses["alpha"].error_code is None
    assert list(catalog.plugins) == ["zulu"]
