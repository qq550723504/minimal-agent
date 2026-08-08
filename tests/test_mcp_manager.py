from __future__ import annotations

from dataclasses import dataclass
import socket

import httpx2
import pytest

from src.agent.mcp.manager import MCPClientManager, MCPConnectionError
from src.agent.mcp.security import ResolvedHTTPConfig, validate_http_config
from src.agent.mcp.transport import PinnedHostAsyncTransport
from src.agent.plugins.models import HTTPMCPServerManifest


@dataclass
class FakeClient:
    connected: bool = False
    exit_count: int = 0
    fail_on_enter: bool = False

    async def __aenter__(self) -> "FakeClient":
        if self.fail_on_enter:
            raise RuntimeError("handshake failed")
        self.connected = True
        return self

    async def __aexit__(self, *_: object) -> None:
        self.connected = False
        self.exit_count += 1


class FakeClientFactory:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.clients: list[FakeClient] = []
        self.fail_at = fail_at

    def __call__(self, _: object) -> FakeClient:
        client = FakeClient(fail_on_enter=len(self.clients) == self.fail_at)
        self.clients.append(client)
        return client


class RecordingTransport(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
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
