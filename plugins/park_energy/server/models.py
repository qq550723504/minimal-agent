from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EnergyQuery(BaseModel):
    park_id: str = Field(min_length=1)
    building_id: str | None = None
    start_time: str
    end_time: str
    energy_type: str = "electricity"
    granularity: Literal["hour", "day", "month"] = "day"


class EnergyTrendRequest(BaseModel):
    startDate: str
    endDate: str
    meterIds: list[str] = Field(default_factory=list)
    projectIds: list[int] = Field(min_length=1)


class EnergyCompareQuery(EnergyQuery):
    compare_start_time: str
    compare_end_time: str


class EnergyResponse(BaseModel):
    success: bool = True
    data: Any = None
    raw: Any = None


def wrap_response(payload: Any) -> dict[str, Any]:
    """Keep a stable envelope while the upstream response contract is pending."""
    if isinstance(payload, dict) and "data" in payload:
        return {"success": True, "data": payload["data"], "raw": payload}
    if isinstance(payload, dict) and "result" in payload:
        return {"success": True, "data": payload["result"], "raw": payload}
    return {"success": True, "data": payload, "raw": payload}
