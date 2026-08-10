from __future__ import annotations

from typing import Any

from .config import Settings
from .models import EnergyCompareQuery, EnergyQuery, wrap_response


class MockEnergyClient:
    """Return deterministic park-energy data without contacting an upstream API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    @staticmethod
    def _query_context(query: EnergyQuery) -> dict[str, Any]:
        return {
            "park_id": query.park_id,
            "building_id": query.building_id,
            "energy_type": query.energy_type,
            "granularity": query.granularity,
            "start_time": query.start_time,
            "end_time": query.end_time,
        }

    async def query_trend(self, query: EnergyQuery) -> dict[str, Any]:
        return wrap_response({
            **self._query_context(query),
            "items": [
                {"timestamp": query.start_time, "value": 120.0, "unit": "kWh"},
                {"timestamp": query.end_time, "value": 135.0, "unit": "kWh"},
            ],
        })

    async def query_ranking(self, query: EnergyQuery) -> dict[str, Any]:
        return wrap_response({
            **self._query_context(query),
            "items": [
                {"building_id": "building-a", "value": 420.0, "unit": "kWh"},
                {"building_id": "building-b", "value": 315.0, "unit": "kWh"},
            ],
        })

    async def get_peak_value(self, query: EnergyQuery) -> dict[str, Any]:
        return wrap_response({
            **self._query_context(query),
            "peak_value": 88.0,
            "peak_time": "12:00:00",
            "unit": "kW",
        })

    async def compare_period(self, query: EnergyCompareQuery) -> dict[str, Any]:
        return wrap_response({
            **self._query_context(query),
            "compare_start_time": query.compare_start_time,
            "compare_end_time": query.compare_end_time,
            "current_total": 1230.0,
            "compare_total": 1175.0,
            "change_rate": 0.0468,
            "unit": "kWh",
        })

    async def get_alarm_summary(self, query: EnergyQuery) -> dict[str, Any]:
        return wrap_response({
            **self._query_context(query),
            "total": 2,
            "critical": 0,
            "warning": 2,
            "items": [
                {"code": "mock-high-usage", "severity": "warning", "count": 2},
            ],
        })
