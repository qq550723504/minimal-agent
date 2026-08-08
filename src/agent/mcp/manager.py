"""Lifecycle ownership for official MCP SDK clients."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AsyncExitStack
from typing import Any, AsyncContextManager

import httpx2
from mcp import Client

from .security import ResolvedHTTPConfig, ResolvedStdioConfig
from .transport import PinnedHostAsyncTransport, http_transport, stdio_transport


class MCPConnectionError(RuntimeError):
    """A stable, secret-free error raised when an MCP client cannot start."""


ResolvedMCPConfig = ResolvedStdioConfig | ResolvedHTTPConfig
ClientFactory = Callable[[Any], AsyncContextManager[Any]]
HTTPConfigResolver = Callable[[ResolvedHTTPConfig], ResolvedHTTPConfig]


class MCPClientManager:
    """Own entered SDK clients and their transport resources until shutdown."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        http_config_resolver: HTTPConfigResolver | None = None,
    ) -> None:
        self._client_factory = Client if client_factory is None else client_factory
        self._http_config_resolver = http_config_resolver
        self._clients: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._configs: dict[str, ResolvedMCPConfig] = {}

    async def start_server(self, server_id: str, config: ResolvedMCPConfig) -> Any:
        """Enter one SDK client, cleaning every started client if setup fails."""
        if server_id in self._clients:
            raise MCPConnectionError("mcp_server_already_started")

        stack = AsyncExitStack()
        try:
            transport = await self._build_transport(config, stack)
            client = await stack.enter_async_context(self._client_factory(transport))
        except Exception:
            failures = await self._close_stacks([stack])
            failures.extend(await self._close_active_servers())
            self._raise_startup_error(failures)

        self._stacks[server_id] = stack
        self._clients[server_id] = client
        self._configs[server_id] = config
        return client

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
