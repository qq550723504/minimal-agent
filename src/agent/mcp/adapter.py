"""Adapt official MCP SDK tools to the capability registry boundary."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from collections.abc import Callable
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


_PLAIN_REMOTE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENCODED_REMOTE_PREFIX = "mcp-encoded-"
_DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 30.0
ClientResolver = Callable[[], Any]


def encode_remote_tool_name(remote_name: str) -> str:
    """Encode an arbitrary SDK tool name into one reversible registry segment."""

    if (
        _PLAIN_REMOTE_NAME.fullmatch(remote_name)
        and not remote_name.startswith(_ENCODED_REMOTE_PREFIX)
    ):
        return remote_name
    return f"{_ENCODED_REMOTE_PREFIX}{remote_name.encode('utf-8').hex()}"


def decode_remote_tool_name(capability_segment: str) -> str:
    """Reverse :func:`encode_remote_tool_name`, rejecting malformed encodings."""

    if not capability_segment.startswith(_ENCODED_REMOTE_PREFIX):
        return capability_segment
    encoded = capability_segment.removeprefix(_ENCODED_REMOTE_PREFIX)
    try:
        decoded = bytes.fromhex(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("invalid_mcp_tool_name_encoding") from error
    if encode_remote_tool_name(decoded) != capability_segment:
        raise ValueError("invalid_mcp_tool_name_encoding")
    return decoded


async def discover_tools(
    client: Any, *, timeout_seconds: float = _DEFAULT_DISCOVERY_TIMEOUT_SECONDS
) -> list[Tool]:
    """Read every SDK tool page in server-provided cursor order."""
    if timeout_seconds <= 0:
        raise ValueError("discovery timeout must be positive")
    cursor: str | None = None
    seen_cursors: set[str | None] = {None}
    tools: list[Tool] = []
    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                result = await client.list_tools(cursor=cursor)
                tools.extend(result.tools)
                cursor = result.next_cursor
                if cursor is None:
                    return tools
                if cursor in seen_cursors:
                    raise MCPToolDiscoveryError("mcp_tool_cursor_cycle")
                seen_cursors.add(cursor)
    except TimeoutError:
        raise MCPToolDiscoveryError("mcp_tool_discovery_timeout") from None


async def register_server_tools(
    plugin_id: str,
    server_id: str,
    client: Any,
    allowed: Iterable[AllowedToolManifest],
    registry: CapabilityRegistry,
    *,
    discovery_timeout_seconds: float = _DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client_resolver: ClientResolver | None = None,
) -> list[ToolSpec]:
    """Discover, validate, and atomically register a server's allowlisted tools."""
    registrations = await prepare_server_tools(
        plugin_id,
        server_id,
        client,
        allowed,
        discovery_timeout_seconds=discovery_timeout_seconds,
        client_resolver=client_resolver,
    )
    registry.register_many(registrations)
    return [spec for spec, _handler in registrations]


async def prepare_server_tools(
    plugin_id: str,
    server_id: str,
    client: Any,
    allowed: Iterable[AllowedToolManifest],
    *,
    discovery_timeout_seconds: float = _DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    client_resolver: ClientResolver | None = None,
) -> list[tuple[ToolSpec, CapabilityHandler]]:
    """Build registry entries without mutating the registry.

    The manager uses this staging boundary to make a whole plugin's tool set
    atomic, rather than registering one server before a later server fails.
    """
    discovered = {
        tool.name: tool
        for tool in await discover_tools(
            client, timeout_seconds=discovery_timeout_seconds
        )
    }
    resolve_client = client_resolver or (lambda: client)
    registrations: list[tuple[ToolSpec, CapabilityHandler]] = []
    for manifest_tool in allowed:
        try:
            remote_tool = discovered[manifest_tool.name]
        except KeyError as error:
            raise MCPToolDiscoveryError("declared_tool_missing") from error

        spec = ToolSpec(
            name=(
                f"{plugin_id}.{server_id}."
                f"{encode_remote_tool_name(remote_tool.name)}"
            ),
            description=remote_tool.description or "",
            input_schema=remote_tool.input_schema,
            source=ToolSource.MCP,
            plugin_id=plugin_id,
            timeout_seconds=manifest_tool.timeout_seconds,
            side_effects=manifest_tool.side_effects,
            idempotent=manifest_tool.idempotent,
            result_size_limit=manifest_tool.result_size_limit,
        )
        registrations.append((spec, _remote_handler(resolve_client, remote_tool.name)))
    return registrations


def _remote_handler(resolve_client: ClientResolver, remote_name: str) -> CapabilityHandler:
    async def invoke(arguments: dict[str, Any], _context: ToolInvocationContext) -> Any:
        client = resolve_client()
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
