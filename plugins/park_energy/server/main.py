from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from mcp.server import MCPServer

from .config import Settings
from .models import EnergyCompareQuery, EnergyQuery
from .mock_client import MockEnergyClient
from .rest_client import EnergyRESTClient


settings = Settings.from_env()
client = MockEnergyClient(settings) if settings.data_mode == "mock" else EnergyRESTClient(settings)
mcp = MCPServer("park-energy")
logger = logging.getLogger(__name__)


def _normalise_query_window(
    park_id: str,
    start_time: str,
    end_time: str,
) -> tuple[str, str, str]:
    """将 LLM 占位参数替换为安全的近期数据时间窗口。

    一些兼容模型会输出示例值，而不是具体的查询参数。基于 Java 的 REST 客户端会忽略
    ``park_id``，但需要有效的日期范围才能返回数据，因此只规范化明显的占位值；
    用户提供的值保持不变。
    """
    values = (park_id, start_time, end_time)
    is_placeholder = any(
        not value.strip() or "PLACEHOLDER" in value.upper() for value in values
    )
    is_example_window = (
        start_time == "2023-01-01T00:00:00Z"
        and end_time == "2023-01-31T23:59:59Z"
    )
    if not (is_placeholder or is_example_window):
        return park_id, start_time, end_time

    configured_start = os.getenv("ENERGY_DEFAULT_START_TIME", "").strip()
    configured_end = os.getenv("ENERGY_DEFAULT_END_TIME", "").strip()
    if configured_start and configured_end:
        default_start, default_end = configured_start, configured_end
    else:
        end = datetime.now(timezone.utc).replace(
            hour=23, minute=59, second=59, microsecond=0
        )
        default_start = (end - timedelta(days=7)).replace(
            hour=0, minute=0, second=0
        ).isoformat().replace("+00:00", "Z")
        default_end = end.isoformat().replace("+00:00", "Z")

    logger.info(
        "normalised energy query placeholders to start_time=%r end_time=%r",
        default_start,
        default_end,
    )
    default_park_id = "park-1" if (
        not park_id.strip() or "PLACEHOLDER" in park_id.upper()
    ) else park_id
    return default_park_id, default_start, default_end
Granularity = Literal["hour", "day", "month"]


@mcp.tool(name="energy.query_trend")
async def query_trend(
    park_id: str,
    start_time: str,
    end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: Granularity = "day",
) -> dict[str, Any]:
    """查询园区或建筑物在一段时间内的能耗。"""
    park_id, start_time, end_time = _normalise_query_window(park_id, start_time, end_time)
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
async def query_ranking(
    park_id: str,
    start_time: str,
    end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: Granularity = "day",
) -> dict[str, Any]:
    """查询所选时间段内的能耗排名。"""
    park_id, start_time, end_time = _normalise_query_window(park_id, start_time, end_time)
    return await client.query_ranking(EnergyQuery(
        park_id=park_id,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
        granularity=granularity,
    ))


@mcp.tool(name="energy.get_peak_value")
async def get_peak_value(
    park_id: str,
    start_time: str,
    end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: Granularity = "day",
) -> dict[str, Any]:
    """查询能耗峰值及其时间戳。"""
    park_id, start_time, end_time = _normalise_query_window(park_id, start_time, end_time)
    return await client.get_peak_value(EnergyQuery(
        park_id=park_id,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
        granularity=granularity,
    ))


@mcp.tool(name="energy.compare_period")
async def compare_period(
    park_id: str,
    start_time: str,
    end_time: str,
    compare_start_time: str,
    compare_end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: Granularity = "day",
) -> dict[str, Any]:
    """比较两个时间段之间的能耗。"""
    return await client.compare_period(EnergyCompareQuery(
        park_id=park_id,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        compare_start_time=compare_start_time,
        compare_end_time=compare_end_time,
        energy_type=energy_type,
        granularity=granularity,
    ))


@mcp.tool(name="energy.get_alarm_summary")
async def get_alarm_summary(
    park_id: str,
    start_time: str,
    end_time: str,
    building_id: str | None = None,
    energy_type: str = "electricity",
    granularity: Granularity = "day",
) -> dict[str, Any]:
    """查询能耗异常和告警汇总。"""
    park_id, start_time, end_time = _normalise_query_window(park_id, start_time, end_time)
    return await client.get_alarm_summary(EnergyQuery(
        park_id=park_id,
        building_id=building_id,
        start_time=start_time,
        end_time=end_time,
        energy_type=energy_type,
        granularity=granularity,
    ))


if __name__ == "__main__":
    mcp.run("streamable-http", host=settings.host, port=settings.port)
