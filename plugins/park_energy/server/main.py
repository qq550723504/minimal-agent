from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .models import EnergyCompareQuery, EnergyQuery
from .rest_client import EnergyRESTClient


settings = Settings.from_env()
client = EnergyRESTClient(settings)
mcp = FastMCP("park-energy")


@mcp.tool(name="energy.query_trend")
async def query_trend(
    park_id: str,
    start_time: str,
    end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: str = "day",
) -> dict[str, Any]:
    """Query energy consumption over time for a park or building."""
    query = EnergyQuery(
        park_id=park_id,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
        granularity=granularity,
    )
    return await client.query_trend(query)


@mcp.tool(name="energy.query_ranking")
async def query_ranking(**kwargs: Any) -> dict[str, Any]:
    """Query energy ranking for the selected period."""
    return await client.query_ranking(EnergyQuery(**kwargs))


@mcp.tool(name="energy.get_peak_value")
async def get_peak_value(**kwargs: Any) -> dict[str, Any]:
    """Query peak energy usage and its timestamp."""
    return await client.get_peak_value(EnergyQuery(**kwargs))


@mcp.tool(name="energy.compare_period")
async def compare_period(**kwargs: Any) -> dict[str, Any]:
    """Compare energy usage between two periods."""
    return await client.compare_period(EnergyCompareQuery(**kwargs))


@mcp.tool(name="energy.get_alarm_summary")
async def get_alarm_summary(**kwargs: Any) -> dict[str, Any]:
    """Query energy anomaly and alarm summary."""
    return await client.get_alarm_summary(EnergyQuery(**kwargs))


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=settings.host, port=settings.port)
