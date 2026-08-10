from __future__ import annotations

import asyncio
import inspect
from typing import Literal, get_type_hints

import pytest

from plugins.park_energy.server.config import Settings
from plugins.park_energy.server import main as park_energy_main
from plugins.park_energy.server.main import (
    compare_period,
    get_alarm_summary,
    get_peak_value,
    mcp,
    query_trend,
    query_ranking,
)
from plugins.park_energy.server.models import EnergyCompareQuery, EnergyQuery
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


def test_data_mode_defaults_to_rest(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PARK_ENERGY_DATA_MODE", raising=False)

    assert Settings.from_env().data_mode == "rest"


def test_data_mode_accepts_mock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARK_ENERGY_DATA_MODE", "mock")

    assert Settings.from_env().data_mode == "mock"


def test_data_mode_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARK_ENERGY_DATA_MODE", "fixture")

    with pytest.raises(ValueError, match="PARK_ENERGY_DATA_MODE"):
        Settings.from_env()


def test_mock_client_returns_repeatable_results(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARK_ENERGY_DATA_MODE", "mock")
    client_type = getattr(park_energy_main, "MockEnergyClient", None)
    assert client_type is not None

    query = EnergyQuery(
        park_id="park-1",
        building_id="building-a",
        start_time="2026-08-01T00:00:00Z",
        end_time="2026-08-02T00:00:00Z",
    )
    comparison = EnergyCompareQuery(
        **query.model_dump(),
        compare_start_time="2026-07-25T00:00:00Z",
        compare_end_time="2026-07-26T00:00:00Z",
    )

    async def collect(client):
        return [
            await client.query_trend(query),
            await client.query_ranking(query),
            await client.get_peak_value(query),
            await client.compare_period(comparison),
            await client.get_alarm_summary(query),
        ]

    first = asyncio.run(collect(client_type(Settings.from_env())))
    second = asyncio.run(collect(client_type(Settings.from_env())))

    assert first == second
    assert all(result["success"] is True for result in first)
    assert first[0]["data"]["items"]
    assert first[1]["data"]["items"]
    assert "peak_value" in first[2]["data"]
    assert "current_total" in first[3]["data"]
    assert "total" in first[4]["data"]
    assert all(result["data"]["park_id"] == "park-1" for result in first)


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
