from __future__ import annotations

import inspect
from typing import Literal, get_type_hints

import pytest

from plugins.park_energy.server.config import Settings
from plugins.park_energy.server.main import (
    compare_period,
    get_alarm_summary,
    get_peak_value,
    mcp,
    query_trend,
    query_ranking,
)
from plugins.park_energy.server.rest_client import EnergyAPIError, EnergyRESTClient


def test_mcp_server_uses_explicit_v2_server_and_tool_parameters():
    from mcp.server import MCPServer

    assert isinstance(mcp, MCPServer)
    for handler in (query_ranking, get_peak_value, get_alarm_summary):
        assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in inspect.signature(handler).parameters.values())
    assert "compare_start_time" in inspect.signature(compare_period).parameters
    assert "compare_end_time" in inspect.signature(compare_period).parameters
    for handler in (query_trend, query_ranking, get_peak_value, compare_period, get_alarm_summary):
        assert get_type_hints(handler)["granularity"] == Literal["hour", "day", "month"]


def test_mcp_host_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PARK_ENERGY_MCP_HOST", raising=False)

    assert Settings.from_env().host == "127.0.0.1"


def test_rest_client_rejects_response_over_configured_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENERGY_API_MAX_RESPONSE_BYTES", "4")

    class Response:
        headers = {"content-length": "5"}

        def raise_for_status(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)

    with pytest.raises(EnergyAPIError, match="response exceeds configured limit"):
        import asyncio

        asyncio.run(EnergyRESTClient(Settings.from_env())._get("/energy", {}))


def test_rest_client_applies_timeout_to_entire_stream(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENERGY_API_TIMEOUT_SECONDS", "0.001")

    class Response:
        headers = {}

        def raise_for_status(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_bytes(self):
            import asyncio

            await asyncio.sleep(0.05)
            yield b"{}"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)

    with pytest.raises(EnergyAPIError, match="timed out"):
        import asyncio

        asyncio.run(EnergyRESTClient(Settings.from_env())._get("/energy", {}))
