"""End-to-end contracts for the official MCP SDK transports."""

from __future__ import annotations

import asyncio
import json
import runpy
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
import pytest

from src.agent.infrastructure.mcp.security import ResolvedHTTPConfig, validate_http_config, validate_stdio_config
from src.agent.infrastructure.mcp.transport import PinnedHostAsyncTransport, http_transport, stdio_transport
from src.agent.infrastructure.plugins.models import HTTPMCPServerManifest, StdioMCPServerManifest


FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "mcp_echo_server.py"


@pytest.mark.anyio
async def test_in_memory_client_contract() -> None:
    """A client connected to an in-memory official server can call its tool."""
    from mcp import Client

    mcp = runpy.run_path(str(FIXTURE_PATH))["mcp"]

    async with Client(mcp) as client:
        result = await client.call_tool("echo", {"message": "in-memory"})

    assert json.loads(result.content[0].text) == {"message": "in-memory"}


@pytest.mark.anyio
async def test_stdio_client_contract() -> None:
    """Only an allowlisted Python executable may launch the echo subprocess."""
    from mcp import Client

    manifest = StdioMCPServerManifest(
        id="echo",
        transport="stdio",
        command=sys.executable,
        args=[str(FIXTURE_PATH)],
        allowed_tools=[],
    )
    config = validate_stdio_config(
        manifest,
        FIXTURE_PATH.parent,
        {sys.executable},
    )

    async with Client(stdio_transport(config)) as client:
        result = await client.call_tool("echo", {"message": "stdio"})

    assert json.loads(result.content[0].text) == {"message": "stdio"}


@pytest.mark.anyio
async def test_streamable_http_client_contract() -> None:
    """The test-only loopback override can use the official HTTP transport."""
    from mcp import Client

    port = _free_loopback_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(FIXTURE_PATH),
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await _wait_for_loopback_listener(port, process)
        config = _loopback_http_config_for_test(port)
        pinned_transport = PinnedHostAsyncTransport(config)
        async with httpx2.AsyncClient(
            follow_redirects=False,
            timeout=httpx2.Timeout(5.0),
            transport=pinned_transport,
            trust_env=False,
        ) as http_client:
            async with Client(http_transport(config, http_client)) as client:
                result = await client.call_tool("echo", {"message": "http"})
    finally:
        _terminate_process(process)

    assert json.loads(result.content[0].text) == {"message": "http"}


def _loopback_http_config_for_test(port: int) -> ResolvedHTTPConfig:
    """Allow HTTP loopback only in this explicit test/development configuration."""
    manifest = HTTPMCPServerManifest(
        id="echo",
        transport="streamable_http",
        url_env="MCP_ECHO_URL",
        allowed_tools=[],
    )
    return validate_http_config(
        manifest,
        {"MCP_ECHO_URL": f"http://127.0.0.1:{port}/mcp"},
        {"127.0.0.1"},
        production=False,
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def _wait_for_loopback_listener(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("MCP echo HTTP fixture exited before accepting connections")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            await asyncio.sleep(0.05)
    raise TimeoutError("MCP echo HTTP fixture did not start on loopback")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
