"""Lifecycle ownership for official MCP SDK clients."""

from __future__ import annotations

from collections.abc import Callable
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


class MCPClientManager:
    """Own entered SDK clients and their transport resources until shutdown."""

    def __init__(self, *, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = Client if client_factory is None else client_factory
        self._clients: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}

    async def start_server(self, server_id: str, config: ResolvedMCPConfig) -> Any:
        """Enter one SDK client, cleaning every started client if setup fails."""
        if server_id in self._clients:
            raise MCPConnectionError("mcp_server_already_started")

        stack = AsyncExitStack()
        try:
            transport = await self._build_transport(config, stack)
            client = await stack.enter_async_context(self._client_factory(transport))
        except Exception as error:
            await stack.aclose()
            await self.close()
            raise MCPConnectionError("mcp_connection_failed") from error

        self._stacks[server_id] = stack
        self._clients[server_id] = client
        return client

    def get_client(self, server_id: str) -> Any:
        """Return an entered client; construction alone never registers one."""
        try:
            return self._clients[server_id]
        except KeyError as error:
            raise MCPConnectionError("mcp_server_not_started") from error

    async def stop_server(self, server_id: str) -> None:
        """Close and forget one entered client and all its transport resources."""
        stack = self._stacks.pop(server_id, None)
        self._clients.pop(server_id, None)
        if stack is not None:
            await stack.aclose()

    async def close(self) -> None:
        """Close all active clients in reverse start order; safe to call repeatedly."""
        stacks = list(self._stacks.values())
        self._stacks.clear()
        self._clients.clear()
        for stack in reversed(stacks):
            await stack.aclose()

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
