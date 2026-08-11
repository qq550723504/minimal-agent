from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from .config import Settings
from .mock_repository import MockSecurityRepository
from .models import (
    CloseEventAction,
    CreateWorkOrder,
    EventAction,
    EventListQuery,
    EventStatus,
    RiskLevel,
)
from .service import SecurityService


settings = Settings.from_env()
service = SecurityService(MockSecurityRepository(), approval_token=settings.approval_token)
mcp = MCPServer("park-security")


@mcp.tool(name="security.get_event_summary")
async def get_event_summary(park_id: str) -> dict[str, Any]:
    """返回指定园区的安防事件风险汇总。"""
    return await service.get_event_summary(park_id)


@mcp.tool(name="security.list_events")
async def list_events(
    park_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
    risk_level: RiskLevel | None = None,
    status: EventStatus | None = None,
) -> dict[str, Any]:
    """按时间、风险等级和状态筛选并返回事件卡片。"""
    return await service.list_events(EventListQuery(
        park_id=park_id,
        start_time=start_time,
        end_time=end_time,
        risk_level=risk_level,
        status=status,
    ))


@mcp.tool(name="security.get_event_detail")
async def get_event_detail(event_id: str) -> dict[str, Any]:
    """返回事件的关联证据、时间线和处置状态。"""
    return await service.get_event_detail(event_id)


@mcp.tool(name="security.get_shift_context")
async def get_shift_context(
    park_id: str,
    area_id: str | None = None,
    at_time: str | None = None,
) -> dict[str, Any]:
    """返回区域值班覆盖、升级规则和空间上下文。"""
    return await service.get_shift_context(park_id, area_id, at_time)


@mcp.tool(name="security.confirm_event")
async def confirm_event(
    event_id: str,
    operator_id: str,
    approval_token: str,
    note: str | None = None,
) -> dict[str, Any]:
    """在人工复核后确认一个开放状态的安防事件。"""
    return await service.confirm_event(EventAction(
        event_id=event_id,
        operator_id=operator_id,
        approval_token=approval_token,
        note=note,
    ))


@mcp.tool(name="security.create_work_order")
async def create_work_order(
    event_id: str,
    operator_id: str,
    assignee: str,
    approval_token: str,
    note: str | None = None,
) -> dict[str, Any]:
    """为已确认的安防事件创建处置工单。"""
    return await service.create_work_order(CreateWorkOrder(
        event_id=event_id,
        operator_id=operator_id,
        assignee=assignee,
        approval_token=approval_token,
        note=note,
    ))


@mcp.tool(name="security.close_event")
async def close_event(
    event_id: str,
    operator_id: str,
    approval_token: str,
    note: str,
) -> dict[str, Any]:
    """关闭已确认或已完成处置的安防事件。"""
    return await service.close_event(CloseEventAction(
        event_id=event_id,
        operator_id=operator_id,
        approval_token=approval_token,
        note=note,
    ))


if __name__ == "__main__":
    mcp.run("streamable-http", host=settings.host, port=settings.port)
