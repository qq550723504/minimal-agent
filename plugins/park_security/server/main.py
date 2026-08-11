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
    """Return the security-event risk summary for a park."""
    return await service.get_event_summary(park_id)


@mcp.tool(name="security.list_events")
async def list_events(
    park_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
    risk_level: RiskLevel | None = None,
    status: EventStatus | None = None,
) -> dict[str, Any]:
    """List event cards after applying the supplied filters."""
    return await service.list_events(EventListQuery(
        park_id=park_id,
        start_time=start_time,
        end_time=end_time,
        risk_level=risk_level,
        status=status,
    ))


@mcp.tool(name="security.get_event_detail")
async def get_event_detail(event_id: str) -> dict[str, Any]:
    """Return all correlated evidence and workflow state for an event."""
    return await service.get_event_detail(event_id)


@mcp.tool(name="security.get_shift_context")
async def get_shift_context(
    park_id: str,
    area_id: str | None = None,
    at_time: str | None = None,
) -> dict[str, Any]:
    """Return duty coverage, escalation rules, and area context."""
    return await service.get_shift_context(park_id, area_id, at_time)


@mcp.tool(name="security.confirm_event")
async def confirm_event(
    event_id: str,
    operator_id: str,
    approval_token: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Confirm an open security event after human review."""
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
    """Create a work order for a confirmed security event."""
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
    """Close a confirmed or remediated security event."""
    return await service.close_event(CloseEventAction(
        event_id=event_id,
        operator_id=operator_id,
        approval_token=approval_token,
        note=note,
    ))


if __name__ == "__main__":
    mcp.run("streamable-http", host=settings.host, port=settings.port)
