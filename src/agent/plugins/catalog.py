"""Read-only records produced while loading administrator-installed plugins."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .models import PluginManifest


@dataclass(frozen=True)
class PluginStatus:
    installation_name: str
    state: Literal["enabled", "disabled"]
    plugin_id: str | None = None
    version: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class LoadedPlugin:
    installation_name: str
    root: Path
    manifest: PluginManifest
    skill_paths: dict[str, Path]


@dataclass
class PluginCatalog:
    plugins: dict[str, LoadedPlugin] = field(default_factory=dict)
    statuses: dict[str, PluginStatus] = field(default_factory=dict)
