"""Safe, deterministic discovery of administrator-installed plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .catalog import LoadedPlugin, PluginCatalog, PluginStatus
from .models import PluginManifest


class PluginLoadError(Exception):
    """A sanitized plugin loading failure suitable for stable status reporting."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


class RequiredPluginError(PluginLoadError):
    """Raised when a plugin declared as required cannot be loaded."""


class PluginLoader:
    def __init__(self, plugin_root: Path):
        self.plugin_root = plugin_root

    def load_all(self) -> PluginCatalog:
        catalog = PluginCatalog()
        if not self.plugin_root.is_dir():
            return catalog

        manifests = sorted(
            self.plugin_root.glob("*/plugin.yaml"), key=lambda path: path.parent.name
        )
        for manifest_path in manifests:
            installation_name = manifest_path.parent.name
            raw_manifest: dict[str, Any] | None = None
            try:
                raw_manifest = _read_yaml_manifest(manifest_path)
                try:
                    manifest = PluginManifest.model_validate(raw_manifest)
                except ValidationError as error:
                    raise PluginLoadError("plugin_manifest_invalid") from error
                if not manifest.enabled:
                    catalog.statuses[installation_name] = PluginStatus(
                        installation_name, "disabled", manifest.id, manifest.version
                    )
                    continue
                if manifest.id in catalog.plugins:
                    raise PluginLoadError("duplicate_plugin_id")

                skill_paths = {
                    skill.id: _validate_skill(manifest_path.parent, skill.path)
                    for skill in manifest.skills
                }
                _validate_mcp_paths(manifest_path.parent, manifest)
            except PluginLoadError as error:
                required = bool(raw_manifest and raw_manifest.get("required") is True)
                if required:
                    raise RequiredPluginError(error.error_code) from None
                catalog.statuses[installation_name] = PluginStatus(
                    installation_name,
                    "disabled",
                    _manifest_value(raw_manifest, "id"),
                    _manifest_value(raw_manifest, "version"),
                    error.error_code,
                )
                continue

            loaded = LoadedPlugin(
                installation_name=installation_name,
                root=manifest_path.parent.resolve(strict=True),
                manifest=manifest,
                skill_paths=skill_paths,
            )
            catalog.plugins[manifest.id] = loaded
            catalog.statuses[installation_name] = PluginStatus(
                installation_name, "enabled", manifest.id, manifest.version
            )
        return catalog


def resolve_inside(root: Path, relative: str) -> Path:
    """Resolve an existing regular path only when it stays inside ``root``.

    Links and Windows junctions are rejected before resolving, so an apparently
    contained path cannot later escape through an administrator-installed link.
    """

    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise PluginLoadError("plugin_path_escape")
    if _is_link_or_junction(root):
        raise PluginLoadError("plugin_path_escape")

    current = root
    for part in relative_path.parts:
        current = current / part
        if current.exists() and _is_link_or_junction(current):
            raise PluginLoadError("plugin_path_escape")

    try:
        root_resolved = root.resolve(strict=True)
        candidate = (root / relative_path).resolve(strict=True)
        candidate.relative_to(root_resolved)
    except FileNotFoundError as error:
        raise PluginLoadError("plugin_skill_missing") from error
    except (OSError, ValueError) as error:
        raise PluginLoadError("plugin_path_escape") from error
    return candidate


def _read_yaml_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise PluginLoadError("plugin_manifest_invalid") from error
    if not isinstance(raw, dict):
        raise PluginLoadError("plugin_manifest_invalid")
    return raw


def _validate_skill(plugin_root: Path, relative_path: str) -> Path:
    path = resolve_inside(plugin_root, relative_path)
    if not path.is_file():
        raise PluginLoadError("plugin_skill_not_file")
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PluginLoadError("plugin_skill_not_utf8") from error
    except OSError as error:
        raise PluginLoadError("plugin_skill_unreadable") from error
    return path


def _validate_mcp_paths(plugin_root: Path, manifest: PluginManifest) -> None:
    for server in manifest.mcp_servers:
        if getattr(server, "cwd", None) is not None:
            resolve_inside(plugin_root, server.cwd)


def _manifest_value(raw_manifest: dict[str, Any] | None, key: str) -> str | None:
    value = raw_manifest.get(key) if raw_manifest else None
    return value if isinstance(value, str) else None


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (bool(is_junction()) if is_junction else False)
