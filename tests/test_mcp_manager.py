from __future__ import annotations

from dataclasses import dataclass
import asyncio
import socket
from pathlib import Path
import sys

import httpx2
import pytest

from src.agent.mcp.manager import MCPClientManager, MCPConnectionError
from src.agent.mcp.security import ResolvedHTTPConfig, validate_http_config, validate_stdio_config
from src.agent.mcp.transport import MCPResponseTooLarge, PinnedHostAsyncTransport
from src.agent.plugins.models import HTTPMCPServerManifest, StdioMCPServerManifest


MCP_FIXTURE = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"


@dataclass
class FakeClient:
    connected: bool = False
    exit_count: int = 0
    fail_on_enter: bool = False
    fail_on_exit: bool = False

    async def __aenter__(self) -> "FakeClient":
        if self.fail_on_enter:
            raise RuntimeError("handshake failed")
        self.connected = True
        return self

    async def __aexit__(self, *_: object) -> None:
        self.connected = False
        self.exit_count += 1
        if self.fail_on_exit:
            raise RuntimeError("client close failed")


class FakeClientFactory:
    def __init__(
        self, *, fail_at: int | None = None, fail_exit_at: int | None = None
    ) -> None:
        self.clients: list[FakeClient] = []
        self.fail_at = fail_at
        self.fail_exit_at = fail_exit_at

    def __call__(self, _: object) -> FakeClient:
        client = FakeClient(
            fail_on_enter=len(self.clients) == self.fail_at,
            fail_on_exit=len(self.clients) == self.fail_exit_at,
        )
        self.clients.append(client)
        return client


class RecordingTransport(httpx2.AsyncBaseTransport):
    def __init__(self, content: bytes = b"ok") -> None:
        self.requests: list[httpx2.Request] = []
        self.content = content

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, request=request, content=self.content)

    async def aclose(self) -> None:
        return None


class FailoverTransport(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        self.hosts: list[str] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.hosts.append(request.url.host)
        if len(self.hosts) == 1:
            raise httpx2.ConnectError("first address unavailable", request=request)
        return httpx2.Response(200, request=request, content=b"ok")

    async def aclose(self) -> None:
        return None


def resolved_http_config(*, address: str = "127.0.0.1") -> ResolvedHTTPConfig:
    return ResolvedHTTPConfig(
        url="https://mcp.example.test/tools",
        hostname="mcp.example.test",
        port=443,
        headers={"Authorization": "Bearer test"},
        addresses=(address,),
    )


@pytest.mark.parametrize(
    "argument",
    [
        "startup_timeout_seconds",
        "discovery_timeout_seconds",
        "shutdown_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_manager_rejects_non_finite_lifecycle_timeouts(argument, value) -> None:
    with pytest.raises(
        ValueError, match="MCP lifecycle timeouts must be finite and positive"
    ):
        MCPClientManager(**{argument: value})


@pytest.mark.anyio
async def test_manager_enters_and_closes_each_client_once() -> None:
    factory = FakeClientFactory()
    manager = MCPClientManager(client_factory=factory)

    assert factory.clients == []
    assert manager.server_ids() == []
    await manager.start_server("demo.remote", resolved_http_config())

    assert manager.get_client("demo.remote").connected is True
    await manager.close()
    assert factory.clients[0].exit_count == 1
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_stop_server_closes_only_the_requested_client() -> None:
    factory = FakeClientFactory()
    manager = MCPClientManager(client_factory=factory)
    await manager.start_server("demo.one", resolved_http_config())
    await manager.start_server("demo.two", resolved_http_config())

    await manager.stop_server("demo.one")

    assert factory.clients[0].exit_count == 1
    assert factory.clients[1].exit_count == 0
    assert manager.server_ids() == ["demo.two"]
    await manager.close()
    assert factory.clients[1].exit_count == 1


@pytest.mark.anyio
async def test_partial_startup_failure_closes_prior_clients() -> None:
    factory = FakeClientFactory(fail_at=1)
    manager = MCPClientManager(client_factory=factory)

    with pytest.raises(MCPConnectionError):
        await manager.start_server("demo.one", resolved_http_config())
        await manager.start_server("demo.two", resolved_http_config())

    await manager.close()
    assert factory.clients[0].exit_count == 1
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_startup_handshake_has_an_explicit_timeout() -> None:
    class HangingClient:
        async def __aenter__(self):
            await asyncio.Event().wait()

        async def __aexit__(self, *_args):
            return None

    manager = MCPClientManager(
        client_factory=lambda _transport: HangingClient(),
        startup_timeout_seconds=0.01,
        shutdown_timeout_seconds=0.01,
    )

    with pytest.raises(MCPConnectionError, match="mcp_startup_timeout"):
        await manager.start_server("demo.remote", resolved_http_config())

    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_shutdown_timeout_still_attempts_other_servers() -> None:
    class HangingExitClient(FakeClient):
        async def __aexit__(self, *_args):
            self.exit_count += 1
            await asyncio.Event().wait()

    first = HangingExitClient()
    second = FakeClient()
    clients = [first, second]

    def factory(_transport):
        return clients.pop(0)

    manager = MCPClientManager(
        client_factory=factory,
        shutdown_timeout_seconds=0.01,
    )
    await manager.start_server("demo.one", resolved_http_config())
    await manager.start_server("demo.two", resolved_http_config())

    with pytest.raises(MCPConnectionError, match="mcp_cleanup_timeout"):
        await manager.close()

    assert [first.exit_count, second.exit_count] == [1, 1]
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_close_attempts_all_servers_when_one_client_exit_fails() -> None:
    factory = FakeClientFactory(fail_exit_at=0)
    manager = MCPClientManager(client_factory=factory)
    await manager.start_server("demo.one", resolved_http_config())
    await manager.start_server("demo.two", resolved_http_config())

    with pytest.raises(MCPConnectionError, match="mcp_cleanup_failed"):
        await manager.close()

    assert [client.exit_count for client in factory.clients] == [1, 1]
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_failed_startup_cleans_prior_clients_when_their_exit_fails() -> None:
    factory = FakeClientFactory(fail_at=1, fail_exit_at=0)
    manager = MCPClientManager(client_factory=factory)
    await manager.start_server("demo.one", resolved_http_config())

    with pytest.raises(MCPConnectionError, match="mcp_connection_failed"):
        await manager.start_server("demo.two", resolved_http_config())

    assert factory.clients[0].exit_count == 1
    assert manager.server_ids() == []


@pytest.mark.anyio
async def test_reconnect_uses_freshly_revalidated_http_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CapturingPinnedTransport(httpx2.AsyncBaseTransport):
        configs: list[ResolvedHTTPConfig] = []

        def __init__(self, config: ResolvedHTTPConfig) -> None:
            self.configs.append(config)

        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            raise AssertionError("the fake lifecycle client must not send requests")

        async def aclose(self) -> None:
            return None

    fresh_config = resolved_http_config(address="127.0.0.2")
    monkeypatch.setattr(
        "src.agent.mcp.manager.PinnedHostAsyncTransport", CapturingPinnedTransport
    )
    manager = MCPClientManager(
        client_factory=FakeClientFactory(),
        http_config_resolver=lambda _: fresh_config,
    )
    await manager.start_server("demo.remote", resolved_http_config())

    await manager.reconnect_server("demo.remote")

    assert [config.addresses for config in CapturingPinnedTransport.configs] == [
        ("127.0.0.1",),
        ("127.0.0.2",),
    ]


@pytest.mark.anyio
async def test_manager_starts_real_stdio_fixture_and_lists_declared_tools() -> None:
    from mcp.types import Tool

    manifest = StdioMCPServerManifest(
        id="local",
        transport="stdio",
        command=sys.executable,
        args=[str(MCP_FIXTURE)],
        allowed_tools=[],
    )
    config = validate_stdio_config(manifest, MCP_FIXTURE.parent, {sys.executable})
    manager = MCPClientManager()

    await manager.start_server("demo.local", config)
    client = manager.get_client("demo.local")
    listing = await client.list_tools()
    await manager.close()

    assert isinstance(listing.tools[0], Tool)
    assert sorted(tool.name for tool in listing.tools) == ["echo", "park_energy"]


@pytest.mark.anyio
async def test_failed_reconnect_keeps_unrelated_clients_alive() -> None:
    factory = FakeClientFactory(fail_at=2)
    manager = MCPClientManager(
        client_factory=factory,
        http_config_resolver=lambda config: config,
    )
    await manager.start_server("demo.one", resolved_http_config())
    await manager.start_server("demo.two", resolved_http_config())

    with pytest.raises(MCPConnectionError, match="mcp_connection_failed"):
        await manager.reconnect_server("demo.one")

    assert manager.server_ids() == ["demo.two"]
    assert factory.clients[1].connected is True
    assert factory.clients[1].exit_count == 0
    await manager.close()


@pytest.mark.anyio
async def test_reconnect_rejects_changed_dns_before_closing_current_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = HTTPMCPServerManifest(
        id="remote",
        transport="streamable_http",
        url_env="DEMO_URL",
        allowed_tools=[],
    )
    factory = FakeClientFactory()

    def refresh(_: ResolvedHTTPConfig) -> ResolvedHTTPConfig:
        monkeypatch.setattr(
            "src.agent.mcp.security.socket.getaddrinfo",
            lambda *_args, **_kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))
            ],
        )
        return validate_http_config(
            manifest,
            {"DEMO_URL": "https://mcp.example.test/tools"},
            {"mcp.example.test"},
            production=True,
        )

    manager = MCPClientManager(
        client_factory=factory,
        http_config_resolver=refresh,
    )
    await manager.start_server("demo.remote", resolved_http_config())

    with pytest.raises(MCPConnectionError, match="mcp_http_revalidation_failed"):
        await manager.reconnect_server("demo.remote")

    assert factory.clients[0].connected is True
    assert factory.clients[0].exit_count == 0
    assert manager.server_ids() == ["demo.remote"]


@pytest.mark.anyio
async def test_pinned_transport_uses_validated_address_after_dns_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolve(address: str):
        return lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
        ]

    manifest = HTTPMCPServerManifest(
        id="remote",
        transport="streamable_http",
        url_env="DEMO_URL",
        allowed_tools=[],
    )
    monkeypatch.setattr("src.agent.mcp.security.socket.getaddrinfo", resolve("127.0.0.1"))
    config = validate_http_config(
        manifest,
        {"DEMO_URL": "https://mcp.example.test/tools"},
        {"mcp.example.test"},
        production=False,
    )
    monkeypatch.setattr("src.agent.mcp.security.socket.getaddrinfo", resolve("169.254.169.254"))
    delegate = RecordingTransport()
    transport = PinnedHostAsyncTransport(config, delegate=delegate)
    client = httpx2.AsyncClient(transport=transport, follow_redirects=False)

    async with client:
        response = await client.get("https://mcp.example.test/tools")

    assert response.status_code == 200
    request = delegate.requests[0]
    assert request.url.host == "127.0.0.1"
    assert request.headers["Host"] == "mcp.example.test"
    assert request.extensions["sni_hostname"] == "mcp.example.test"


@pytest.mark.anyio
async def test_pinned_transport_fails_over_across_validated_addresses() -> None:
    config = ResolvedHTTPConfig(
        url="https://mcp.example.test/tools",
        hostname="mcp.example.test",
        port=443,
        headers={},
        addresses=("2001:db8::1", "192.0.2.10"),
    )
    delegate = FailoverTransport()
    transport = PinnedHostAsyncTransport(config, delegate=delegate)

    async with httpx2.AsyncClient(transport=transport) as client:
        response = await client.get(config.url)

    assert response.status_code == 200
    assert delegate.hosts == ["2001:db8::1", "192.0.2.10"]


@pytest.mark.anyio
async def test_pinned_transport_enforces_response_size_cap() -> None:
    config = ResolvedHTTPConfig(
        url="https://mcp.example.test/tools",
        hostname="mcp.example.test",
        port=443,
        headers={},
        addresses=("192.0.2.10",),
    )
    transport = PinnedHostAsyncTransport(
        config, delegate=RecordingTransport(b"four"), max_response_bytes=3
    )

    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(MCPResponseTooLarge, match="mcp_response_too_large"):
            await client.get(config.url)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("url", "port", "expected_host"),
    [
        ("https://[::1]/tools", 443, "[::1]"),
        ("https://[::1]:8443/tools", 8443, "[::1]:8443"),
    ],
)
async def test_pinned_transport_preserves_bracketed_ipv6_host_header(
    url: str, port: int, expected_host: str
) -> None:
    config = ResolvedHTTPConfig(
        url=url,
        hostname="::1",
        port=port,
        headers={},
        addresses=("::1",),
    )
    delegate = RecordingTransport()
    transport = PinnedHostAsyncTransport(config, delegate=delegate)

    async with httpx2.AsyncClient(transport=transport) as client:
        await client.get(url)

    assert delegate.requests[0].headers["Host"] == expected_host


@pytest.mark.anyio
async def test_pinned_transport_accepts_trailing_dot_hostname() -> None:
    config = ResolvedHTTPConfig(
        url="https://mcp.example.test./tools",
        hostname="mcp.example.test",
        port=443,
        headers={},
        addresses=("127.0.0.1",),
    )
    delegate = RecordingTransport()
    transport = PinnedHostAsyncTransport(config, delegate=delegate)

    async with httpx2.AsyncClient(transport=transport) as client:
        await client.get(config.url)

    assert delegate.requests[0].url.host == "127.0.0.1"
    assert delegate.requests[0].headers["Host"] == "mcp.example.test."


@pytest.mark.anyio
async def test_pinned_transport_uses_ascii_idn_authority_with_trailing_dot() -> None:
    config = ResolvedHTTPConfig(
        url="https://täst.example./tools",
        hostname="xn--tst-qla.example",
        port=443,
        headers={},
        addresses=("127.0.0.1",),
    )
    delegate = RecordingTransport()
    transport = PinnedHostAsyncTransport(config, delegate=delegate)

    async with httpx2.AsyncClient(transport=transport) as client:
        await client.get(config.url)

    assert delegate.requests[0].headers["Host"] == "xn--tst-qla.example."
