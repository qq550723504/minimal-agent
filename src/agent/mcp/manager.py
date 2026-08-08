"""Lifecycle ownership for official MCP SDK clients."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from contextlib import AsyncExitStack
from typing import Any, AsyncContextManager

import httpx2
from mcp import Client

from src.agent import config
from src.agent.capabilities.registry import CapabilityRegistry
from src.agent.plugins.catalog import LoadedPlugin, PluginCatalog
from src.agent.plugins.loader import RequiredPluginError
from src.agent.plugins.models import HTTPMCPServerManifest, MCPServerManifest, StdioMCPServerManifest

from .adapter import MCPToolDiscoveryError, prepare_server_tools
from .security import (
    MCPSecurityError,
    ResolvedHTTPConfig,
    ResolvedStdioConfig,
    validate_http_config,
    validate_stdio_config,
)
from .transport import PinnedHostAsyncTransport, http_transport, stdio_transport


class MCPConnectionError(RuntimeError):
    """A stable, secret-free error raised when an MCP client cannot start."""


ResolvedMCPConfig = ResolvedStdioConfig | ResolvedHTTPConfig
ClientFactory = Callable[[Any], AsyncContextManager[Any]]
HTTPConfigResolver = Callable[[ResolvedHTTPConfig], ResolvedHTTPConfig]
ServerConfigResolver = Callable[[LoadedPlugin, MCPServerManifest], ResolvedMCPConfig]


class MCPClientManager:
    """Own entered SDK clients and their transport resources until shutdown."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        http_config_resolver: HTTPConfigResolver | None = None,
        server_config_resolver: ServerConfigResolver | None = None,
    ) -> None:
        self._client_factory = Client if client_factory is None else client_factory
        self._http_config_resolver = http_config_resolver
        self._server_config_resolver = (
            self._resolve_catalog_server
            if server_config_resolver is None
            else server_config_resolver
        )
        self._clients: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._configs: dict[str, ResolvedMCPConfig] = {}

    async def start_server(self, server_id: str, config: ResolvedMCPConfig) -> Any:
        """Enter one SDK client, cleaning every started client if setup fails."""
        return await self._start_server(server_id, config, cleanup_active_on_failure=True)

    async def start_catalog(
        self, catalog: PluginCatalog, registry: CapabilityRegistry
    ) -> None:
        """Start plugins deterministically and publish each plugin's tools atomically."""
        attempt_server_ids: list[str] = []
        attempt_tool_names: list[str] = []
        for plugin_id, plugin in sorted(catalog.plugins.items()):
            started_server_ids: list[str] = []
            registrations = []
            try:
                for server in sorted(plugin.manifest.mcp_servers, key=lambda item: item.id):
                    server_key = f"{plugin_id}.{server.id}"
                    server_config = self._server_config_resolver(plugin, server)
                    client = await self._start_server(
                        server_key, server_config, cleanup_active_on_failure=False
                    )
                    started_server_ids.append(server_key)
                    registrations.extend(
                        await prepare_server_tools(
                            plugin_id,
                            server.id,
                            client,
                            server.allowed_tools,
                        )
                    )
                registry.register_many(registrations)
                attempt_server_ids.extend(started_server_ids)
                attempt_tool_names.extend(spec.name for spec, _handler in registrations)
            except Exception as error:
                await self._stop_catalog_servers(started_server_ids)
                error_code = self._catalog_error_code(error)
                catalog.disable_plugin(plugin_id, error_code)
                if plugin.manifest.required:
                    await self._rollback_catalog_attempt(
                        attempt_server_ids, attempt_tool_names, registry
                    )
                    raise RequiredPluginError(error_code) from None

    async def _start_server(
        self,
        server_id: str,
        config: ResolvedMCPConfig,
        *,
        cleanup_active_on_failure: bool,
    ) -> Any:
        """Enter a server, optionally retaining independently started clients on failure."""
        if server_id in self._clients:
            raise MCPConnectionError("mcp_server_already_started")

        stack = AsyncExitStack()
        try:
            transport = await self._build_transport(config, stack)
            client = await stack.enter_async_context(self._client_factory(transport))
        except Exception:
            failures = await self._close_stacks([stack])
            if cleanup_active_on_failure:
                failures.extend(await self._close_active_servers())
            self._raise_startup_error(failures)

        self._stacks[server_id] = stack
        self._clients[server_id] = client
        self._configs[server_id] = config
        return client

    async def _stop_catalog_servers(self, server_ids: Iterable[str]) -> None:
        """Best-effort cleanup for one failed plugin without touching other plugins."""
        for server_id in reversed(list(server_ids)):
            try:
                await self.stop_server(server_id)
            except MCPConnectionError:
                continue

    async def _rollback_catalog_attempt(
        self,
        server_ids: Iterable[str],
        tool_names: Iterable[str],
        registry: CapabilityRegistry,
    ) -> None:
        """Undo only clients and tools created during this failed catalog start."""
        await self._stop_catalog_servers(server_ids)
        for tool_name in tool_names:
            registry.unregister(tool_name)

    @staticmethod
    def _catalog_error_code(error: Exception) -> str:
        if isinstance(error, (MCPToolDiscoveryError, MCPSecurityError, MCPConnectionError)):
            return str(error)
        if isinstance(error, ValueError) and str(error).startswith("duplicate tool:"):
            return "mcp_tool_namespace_collision"
        return "mcp_plugin_start_failed"

    @staticmethod
    def _resolve_catalog_server(
        plugin: LoadedPlugin, server: MCPServerManifest
    ) -> ResolvedMCPConfig:
        if isinstance(server, StdioMCPServerManifest):
            return validate_stdio_config(
                server,
                plugin.root,
                config.MCP_STDIO_ALLOWED_COMMANDS,
            )
        if isinstance(server, HTTPMCPServerManifest):
            return validate_http_config(
                server,
                os.environ,
                config.MCP_ALLOWED_HOSTS,
                production=True,
            )
        raise MCPConnectionError("mcp_server_config_invalid")

    def get_client(self, server_id: str) -> Any:
        """Return an entered client; construction alone never registers one."""
        try:
            return self._clients[server_id]
        except KeyError as error:
            raise MCPConnectionError("mcp_server_not_started") from error

    async def stop_server(self, server_id: str) -> None:
        """Close and forget one entered client and all its transport resources."""
        stack = self._stacks.get(server_id)
        if stack is not None:
            failures = await self._close_stacks([stack])
            self._stacks.pop(server_id, None)
            self._clients.pop(server_id, None)
            self._configs.pop(server_id, None)
            self._raise_sanitized_error("mcp_cleanup_failed", failures)

    async def reconnect_server(self, server_id: str) -> Any:
        """Re-enter a server only after its HTTP configuration is freshly validated."""
        try:
            current_config = self._configs[server_id]
        except KeyError as error:
            raise MCPConnectionError("mcp_server_not_started") from error

        config = current_config
        if isinstance(current_config, ResolvedHTTPConfig):
            if self._http_config_resolver is None:
                raise MCPConnectionError("mcp_http_revalidation_required")
            try:
                config = self._http_config_resolver(current_config)
            except Exception:
                raise MCPConnectionError("mcp_http_revalidation_failed") from None
            if not isinstance(config, ResolvedHTTPConfig):
                raise MCPConnectionError("mcp_http_revalidation_failed")

        await self.stop_server(server_id)
        return await self.start_server(server_id, config)

    async def close(self) -> None:
        """Close all active clients in reverse start order; safe to call repeatedly."""
        failures = await self._close_active_servers()
        self._raise_sanitized_error("mcp_cleanup_failed", failures)

    async def _close_active_servers(self) -> list[Exception]:
        """Attempt every active stack before forgetting their registration state."""
        failures = await self._close_stacks(reversed(self._stacks.values()))
        self._stacks.clear()
        self._clients.clear()
        self._configs.clear()
        return failures

    @staticmethod
    async def _close_stacks(stacks: Iterable[AsyncExitStack]) -> list[Exception]:
        """Run every cleanup stack, retaining only sanitized failure cardinality."""
        failures: list[Exception] = []
        for stack in stacks:
            try:
                await stack.aclose()
            except Exception as error:
                failures.append(error)
        return failures

    @staticmethod
    def _raise_sanitized_error(code: str, failures: list[Exception]) -> None:
        if not failures:
            return
        sanitized = ExceptionGroup(
            "mcp_cleanup_failures",
            [RuntimeError("mcp_cleanup_callback_failed") for _ in failures],
        )
        raise MCPConnectionError(code) from sanitized

    @classmethod
    def _raise_startup_error(cls, failures: list[Exception]) -> None:
        if failures:
            cls._raise_sanitized_error("mcp_connection_failed", failures)
        raise MCPConnectionError("mcp_connection_failed") from None

    def server_ids(self) -> list[str]:
        """Return active server IDs in their startup order."""
        return list(self._clients)

    async def _build_transport(
        self, config: ResolvedMCPConfig, stack: AsyncExitStack
    ) -> AsyncContextManager[Any]:
        if isinstance(config, ResolvedStdioConfig):
            return stdio_transport(config)

        pinned_transport = PinnedHostAsyncTransport(config)
        http_client = await stack.enter_async_context(
            httpx2.AsyncClient(
                headers=config.headers,
                follow_redirects=False,
                timeout=httpx2.Timeout(30.0, read=300.0),
                transport=pinned_transport,
                trust_env=False,
            )
        )
        return http_transport(config, http_client)
