"""Declarative plugin contracts and safe local-plugin loading."""

from .catalog import LoadedPlugin, PluginCatalog, PluginStatus
from .loader import PluginLoader, PluginLoadError, RequiredPluginError
from .models import PluginManifest

__all__ = [
    "LoadedPlugin",
    "PluginCatalog",
    "PluginLoader",
    "PluginLoadError",
    "PluginManifest",
    "PluginStatus",
    "RequiredPluginError",
]
