from __future__ import annotations

import asyncio
import inspect
from typing import Literal, get_type_hints

import pytest
import httpx

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


def test_query_ranking_normalises_model_placeholder_window(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class Client:
        async def query_ranking(self, query):
            captured.update(query.model_dump())
            return {"success": True, "data": {"items": []}}

    monkeypatch.setattr(park_energy_main, "client", Client())
    monkeypatch.setenv("ENERGY_DEFAULT_START_TIME", "2026-08-07T00:00:00Z")
    monkeypatch.setenv("ENERGY_DEFAULT_END_TIME", "2026-08-14T23:59:59Z")

    result = asyncio.run(query_ranking(
        park_id="PARK_ID_PLACEHOLDER",
        start_time="2023-01-01T00:00:00Z",
        end_time="2023-01-31T23:59:59Z",
    ))

    assert result["success"] is True
    assert captured == {
        "park_id": "park-1",
        "building_id": None,
        "start_time": "2026-08-07T00:00:00Z",
        "end_time": "2026-08-14T23:59:59Z",
        "energy_type": "electricity",
        "granularity": "day",
    }


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


def test_rest_trend_posts_java_agent_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENERGY_PROJECT_IDS", "101")
    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        headers = {"content-length": "34"}

        def raise_for_status(self):
            return None

        async def aread(self):
            return b'{"code":200,"data":{"total":5}}'

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)
    query = EnergyQuery(
        park_id="park-1",
        building_id=None,
        start_time="2026-08-04T00:00:00Z",
        end_time="2026-08-10T23:59:59Z",
    )

    result = asyncio.run(EnergyRESTClient(Settings.from_env()).query_trend(query))

    assert captured["url"] == "http://localhost:9000/api/agent/v1/energy/trend"
    assert captured["json"] == {
        "startDate": "2026-08-04",
        "endDate": "2026-08-10",
        "meterIds": [],
        "projectIds": [101],
    }
    assert result["data"]["total"] == 5


def test_rest_trend_accepts_cent_common_success_code(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENERGY_PROJECT_IDS", "2709")

    class Response:
        status_code = 200
        headers = {"content-length": "48"}

        def raise_for_status(self):
            return None

        async def aread(self):
            return b'{"code":1000,"state":true,"result":{"total":720}}'

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)
    query = EnergyQuery(
        park_id="park-1",
        start_time="2026-08-04T00:00:00Z",
        end_time="2026-08-10T23:59:59Z",
    )
    result = asyncio.run(EnergyRESTClient(Settings.from_env()).query_trend(query))
    assert result["data"]["total"] == 720


def test_rest_peak_derives_from_java_trend_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENERGY_PROJECT_IDS", "2709")
    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        headers = {"content-length": "90"}

        def raise_for_status(self):
            return None

        async def aread(self):
            return b'{"code":1000,"state":true,"result":{"peak":{"date":"2026-08-06","energy":88.5}}}'

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)
    query = EnergyQuery(
        park_id="park-1",
        start_time="2026-08-04T00:00:00Z",
        end_time="2026-08-10T23:59:59Z",
    )

    result = asyncio.run(EnergyRESTClient(Settings.from_env()).get_peak_value(query))

    assert captured["url"] == "http://localhost:9000/api/agent/v1/energy/trend"
    assert captured["json"]["projectIds"] == [2709]
    assert result["data"] == {"peak_value": 88.5, "peak_time": "2026-08-06"}


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (500, b'{"code":500,"message":"failed"}', "HTTP 500"),
        (200, b'{"code":500,"message":"failed"}', "business failure"),
        (200, b"not-json", "invalid JSON"),
    ],
)
def test_rest_trend_converts_upstream_failures(monkeypatch: pytest.MonkeyPatch, status, body, message):
    monkeypatch.setenv("ENERGY_PROJECT_IDS", "101")

    class Response:
        status_code = status
        headers = {"content-length": str(len(body))}

        def raise_for_status(self):
            if self.status_code >= 400:
                request = httpx.Request("POST", "http://energy.test")
                raise httpx.HTTPStatusError("failed", request=request, response=self)

        async def aread(self):
            return body

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            return Response()

    monkeypatch.setattr("plugins.park_energy.server.rest_client.httpx.AsyncClient", Client)
    query = EnergyQuery(
        park_id="park-1",
        start_time="2026-08-04T00:00:00Z",
        end_time="2026-08-10T23:59:59Z",
    )

    with pytest.raises(EnergyAPIError, match=message):
        asyncio.run(EnergyRESTClient(Settings.from_env()).query_trend(query))
