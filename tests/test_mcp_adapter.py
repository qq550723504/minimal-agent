from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import TextContent, Tool

from src.agent.capabilities.models import ToolCall, ToolInvocationContext, ToolSource, ToolSpec
from src.agent.capabilities.registry import CapabilityRegistry
from src.agent.mcp.manager import MCPClientManager
from src.agent.mcp.security import ResolvedHTTPConfig
from src.agent.plugins.catalog import LoadedPlugin, PluginCatalog, PluginStatus
from src.agent.plugins.loader import RequiredPluginError
from src.agent.plugins.models import PluginManifest
from src.agent.plugins.models import AllowedToolManifest


class FakeMCPClient:
    def __init__(self, pages: dict[str | None, object]) -> None:
        self._pages = pages
        self.cursors: list[str | None] = []
        self.call_result = SimpleNamespace(
            is_error=False,
            structured_content=None,
            content=[TextContent(text="ok")],
        )
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self, *, cursor: str | None = None):
        self.cursors.append(cursor)
        return self._pages[cursor]

    async def call_tool(self, name: str, arguments: dict | None = None):
        self.calls.append((name, arguments or {}))
        return self.call_result


class CatalogClient(FakeMCPClient):
    def __init__(self, pages: dict[str | None, object]) -> None:
        super().__init__(pages)
        self.exit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exit_count += 1


class CatalogClientFactory:
    def __init__(self, clients: list[CatalogClient]) -> None:
        self.clients = clients

    def __call__(self, _transport: object) -> CatalogClient:
        return self.clients.pop(0)


def remote_tool(name: str, *, description: str = "") -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={"type": "object", "additionalProperties": False},
    )


def page(tools: list[Tool], next_cursor: str | None = None):
    return SimpleNamespace(tools=tools, next_cursor=next_cursor)


def resolved_config() -> ResolvedHTTPConfig:
    return ResolvedHTTPConfig(
        url="https://mcp.example.test/tools",
        hostname="mcp.example.test",
        port=443,
        headers={},
        addresses=("127.0.0.1",),
    )


def catalog_with_plugin(*, required: bool, servers: list[dict]) -> PluginCatalog:
    manifest = PluginManifest.model_validate(
        {
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "required": required,
            "mcp_servers": servers,
        }
    )
    loaded = LoadedPlugin("demo-install", Path("."), manifest, {})
    return PluginCatalog(
        plugins={"demo": loaded},
        statuses={
            "demo-install": PluginStatus(
                "demo-install", "enabled", "demo", "1.0.0"
            )
        },
    )


@pytest.mark.anyio
async def test_discovery_paginates_and_registers_only_allowlist() -> None:
    from src.agent.mcp.adapter import register_server_tools

    client = FakeMCPClient(
        {
            None: page([remote_tool("first")], "next"),
            "next": page([remote_tool("second", description="The approved tool")]),
        }
    )
    registry = CapabilityRegistry()

    registered = await register_server_tools(
        plugin_id="demo",
        server_id="remote",
        client=client,
        allowed=[AllowedToolManifest(name="second", side_effects=False, idempotent=True)],
        registry=registry,
    )

    assert [spec.name for spec in registered] == ["demo.remote.second"]
    assert registered[0].description == "The approved tool"
    assert registered[0].source is ToolSource.MCP
    assert client.cursors == [None, "next"]
    assert [spec.name for spec in registry.list_specs()] == ["demo.remote.second"]


@pytest.mark.anyio
async def test_missing_declared_tool_registers_nothing() -> None:
    from src.agent.mcp.adapter import MCPToolDiscoveryError, register_server_tools

    registry = CapabilityRegistry()
    client = FakeMCPClient({None: page([])})

    with pytest.raises(MCPToolDiscoveryError, match="declared_tool_missing"):
        await register_server_tools(
            "demo",
            "remote",
            client,
            [AllowedToolManifest(name="required", side_effects=False, idempotent=True)],
            registry,
        )

    assert registry.list_specs() == []


@pytest.mark.anyio
async def test_remote_error_is_not_treated_as_success() -> None:
    from src.agent.mcp.adapter import register_server_tools

    client = FakeMCPClient({None: page([remote_tool("search")])})
    client.call_result = SimpleNamespace(
        is_error=True,
        structured_content=None,
        content=[TextContent(text="denied")],
    )
    registry = CapabilityRegistry()
    await register_server_tools(
        "demo",
        "remote",
        client,
        [AllowedToolManifest(name="search", side_effects=False, idempotent=True)],
        registry,
    )

    result = await registry.invoke(
        ToolCall(call_id="1", tool="demo.remote.search", arguments={}),
        ToolInvocationContext(),
    )

    assert (result.status, result.error_code) == ("error", "mcp_tool_error")
    assert client.calls == [("search", {})]


@pytest.mark.anyio
async def test_structured_content_is_preserved() -> None:
    from src.agent.mcp.adapter import register_server_tools

    client = FakeMCPClient({None: page([remote_tool("search")])})
    client.call_result = SimpleNamespace(
        is_error=False,
        structured_content={"matches": [{"id": 7}]},
        content=[TextContent(text="untrusted fallback")],
    )
    registry = CapabilityRegistry()
    await register_server_tools(
        "demo",
        "remote",
        client,
        [AllowedToolManifest(name="search", side_effects=False, idempotent=True)],
        registry,
    )

    result = await registry.invoke(
        ToolCall(call_id="1", tool="demo.remote.search", arguments={}),
        ToolInvocationContext(),
    )

    assert result.content == {"matches": [{"id": 7}]}


@pytest.mark.anyio
async def test_text_blocks_remain_typed_list() -> None:
    from src.agent.mcp.adapter import register_server_tools

    client = FakeMCPClient({None: page([remote_tool("search")])})
    client.call_result = SimpleNamespace(
        is_error=False,
        structured_content=None,
        content=[TextContent(text='{"not": "combined"}'), TextContent(text="second")],
    )
    registry = CapabilityRegistry()
    await register_server_tools(
        "demo",
        "remote",
        client,
        [AllowedToolManifest(name="search", side_effects=False, idempotent=True)],
        registry,
    )

    result = await registry.invoke(
        ToolCall(call_id="1", tool="demo.remote.search", arguments={}),
        ToolInvocationContext(),
    )

    assert result.content == [
        {"type": "text", "text": '{"not": "combined"}'},
        {"type": "text", "text": "second"},
    ]


@pytest.mark.anyio
async def test_namespace_collision_is_atomic() -> None:
    from src.agent.mcp.adapter import register_server_tools

    registry = CapabilityRegistry()
    registry.register(
        ToolSpec(
            name="demo.remote.existing",
            input_schema={"type": "object"},
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
        ),
        lambda _arguments, _context: None,
    )
    client = FakeMCPClient(
        {None: page([remote_tool("fresh"), remote_tool("existing")])}
    )

    with pytest.raises(ValueError, match="duplicate tool: demo.remote.existing"):
        await register_server_tools(
            "demo",
            "remote",
            client,
            [
                AllowedToolManifest(name="fresh", side_effects=False, idempotent=True),
                AllowedToolManifest(name="existing", side_effects=False, idempotent=True),
            ],
            registry,
        )

    assert [spec.name for spec in registry.list_specs()] == ["demo.remote.existing"]


@pytest.mark.anyio
async def test_optional_plugin_failure_closes_all_its_clients_and_registers_nothing() -> None:
    catalog = catalog_with_plugin(
        required=False,
        servers=[
            {
                "id": "first",
                "transport": "streamable_http",
                "url_env": "FIRST_URL",
                "allowed_tools": [
                    {"name": "one", "side_effects": False, "idempotent": True}
                ],
            },
            {
                "id": "second",
                "transport": "streamable_http",
                "url_env": "SECOND_URL",
                "allowed_tools": [
                    {"name": "missing", "side_effects": False, "idempotent": True}
                ],
            },
        ],
    )
    first = CatalogClient({None: page([remote_tool("one")])})
    second = CatalogClient({None: page([])})
    manager = MCPClientManager(
        client_factory=CatalogClientFactory([first, second]),
        server_config_resolver=lambda _plugin, _server: resolved_config(),
    )
    registry = CapabilityRegistry()

    await manager.start_catalog(catalog, registry)

    assert registry.list_specs() == []
    assert first.exit_count == second.exit_count == 1
    assert manager.server_ids() == []
    assert catalog.statuses["demo-install"].state == "disabled"
    assert catalog.statuses["demo-install"].error_code == "declared_tool_missing"


@pytest.mark.anyio
async def test_required_plugin_failure_is_sanitized_and_closes_its_clients() -> None:
    catalog = catalog_with_plugin(
        required=True,
        servers=[
            {
                "id": "remote",
                "transport": "streamable_http",
                "url_env": "REMOTE_URL",
                "allowed_tools": [
                    {"name": "missing", "side_effects": False, "idempotent": True}
                ],
            }
        ],
    )
    client = CatalogClient({None: page([])})
    manager = MCPClientManager(
        client_factory=CatalogClientFactory([client]),
        server_config_resolver=lambda _plugin, _server: resolved_config(),
    )

    with pytest.raises(RequiredPluginError, match="declared_tool_missing"):
        await manager.start_catalog(catalog, CapabilityRegistry())

    assert client.exit_count == 1
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_required_failure_rolls_back_earlier_plugins_but_keeps_preexisting_tools() -> None:
    first_catalog = catalog_with_plugin(
        required=False,
        servers=[
            {
                "id": "remote",
                "transport": "streamable_http",
                "url_env": "FIRST_URL",
                "allowed_tools": [
                    {"name": "approved", "side_effects": False, "idempotent": True}
                ],
            }
        ],
    )
    first_plugin = first_catalog.plugins.pop("demo")
    first_status = first_catalog.statuses.pop("demo-install")
    required_manifest = PluginManifest.model_validate(
        {
            "api_version": "minimal-agent/v1",
            "id": "required",
            "version": "1.0.0",
            "required": True,
            "mcp_servers": [
                {
                    "id": "remote",
                    "transport": "streamable_http",
                    "url_env": "REQUIRED_URL",
                    "allowed_tools": [
                        {"name": "missing", "side_effects": False, "idempotent": True}
                    ],
                }
            ],
        }
    )
    required_plugin = LoadedPlugin("required-install", Path("."), required_manifest, {})
    catalog = PluginCatalog(
        plugins={"demo": first_plugin, "required": required_plugin},
        statuses={
            first_status.installation_name: first_status,
            "required-install": PluginStatus(
                "required-install", "enabled", "required", "1.0.0"
            ),
        },
    )
    preexisting = ToolSpec(
        name="preexisting.local",
        input_schema={"type": "object"},
        source=ToolSource.LOCAL,
        side_effects=False,
        idempotent=True,
    )
    registry = CapabilityRegistry()
    registry.register(preexisting, lambda _arguments, _context: None)
    first_client = CatalogClient({None: page([remote_tool("approved")])})
    required_client = CatalogClient({None: page([])})
    manager = MCPClientManager(
        client_factory=CatalogClientFactory([first_client, required_client]),
        server_config_resolver=lambda _plugin, _server: resolved_config(),
    )

    with pytest.raises(RequiredPluginError, match="declared_tool_missing"):
        await manager.start_catalog(catalog, registry)

    assert first_client.exit_count == required_client.exit_count == 1
    assert manager.server_ids() == []
    assert [spec.name for spec in registry.list_specs()] == ["preexisting.local"]
