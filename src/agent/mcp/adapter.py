"""Adapt official MCP SDK tools to the capability registry boundary."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp.types import Tool

from src.agent.capabilities.errors import ToolExecutionError
from src.agent.capabilities.models import ToolInvocationContext, ToolSource, ToolSpec
from src.agent.capabilities.registry import CapabilityHandler, CapabilityRegistry
from src.agent.plugins.models import AllowedToolManifest


class MCPToolDiscoveryError(RuntimeError):
    """A stable discovery failure that does not disclose remote tool details."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


async def discover_tools(client: Any) -> list[Tool]:
    """Read every SDK tool page in server-provided cursor order."""
    cursor: str | None = None
    tools: list[Tool] = []
    while True:
        result = await client.list_tools(cursor=cursor)
        tools.extend(result.tools)
        cursor = result.next_cursor
        if cursor is None:
            return tools


async def register_server_tools(
    plugin_id: str,
    server_id: str,
    client: Any,
    allowed: Iterable[AllowedToolManifest],
    registry: CapabilityRegistry,
) -> list[ToolSpec]:
    """Discover, validate, and atomically register a server's allowlisted tools."""
    registrations = await prepare_server_tools(plugin_id, server_id, client, allowed)
    registry.register_many(registrations)
    return [spec for spec, _handler in registrations]


async def prepare_server_tools(
    plugin_id: str,
    server_id: str,
    client: Any,
    allowed: Iterable[AllowedToolManifest],
) -> list[tuple[ToolSpec, CapabilityHandler]]:
    """Build registry entries without mutating the registry.

    The manager uses this staging boundary to make a whole plugin's tool set
    atomic, rather than registering one server before a later server fails.
    """
    discovered = {tool.name: tool for tool in await discover_tools(client)}
    registrations: list[tuple[ToolSpec, CapabilityHandler]] = []
    for manifest_tool in allowed:
        try:
            remote_tool = discovered[manifest_tool.name]
        except KeyError as error:
            raise MCPToolDiscoveryError("declared_tool_missing") from error

        spec = ToolSpec(
            name=f"{plugin_id}.{server_id}.{remote_tool.name}",
            description=remote_tool.description or "",
            input_schema=remote_tool.input_schema,
            source=ToolSource.MCP,
            plugin_id=plugin_id,
            timeout_seconds=manifest_tool.timeout_seconds,
            side_effects=manifest_tool.side_effects,
            idempotent=manifest_tool.idempotent,
            result_size_limit=manifest_tool.result_size_limit,
        )
        registrations.append((spec, _remote_handler(client, remote_tool.name)))
    return registrations


def _remote_handler(client: Any, remote_name: str) -> CapabilityHandler:
    async def invoke(arguments: dict[str, Any], _context: ToolInvocationContext) -> Any:
        result = await client.call_tool(remote_name, arguments)
        if result.is_error:
            raise ToolExecutionError("mcp_tool_error", retryable=False)
        if result.structured_content is not None:
            return result.structured_content
        return _text_content_blocks(result.content)

    return invoke


def _text_content_blocks(content: Iterable[Any]) -> list[dict[str, str]]:
    """Retain supported text blocks without parsing or combining untrusted text."""
    return [
        {"type": "text", "text": block.text}
        for block in content
        if getattr(block, "type", None) == "text" and isinstance(getattr(block, "text", None), str)
    ]
