from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings
from .models import EnergyCompareQuery, EnergyQuery, wrap_response


class EnergyAPIError(RuntimeError):
    """An upstream energy API request failed or returned invalid data."""


class EnergyRESTClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def _headers(self) -> dict[str, str]:
        if not self.settings.api_token:
            return {}
        value = self.settings.api_token
        if self.settings.token_prefix:
            value = f"{self.settings.token_prefix} {value}"
        return {self.settings.token_header: value}

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.settings.api_base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                async with client.stream("GET", url, params=params, headers=self._headers()) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self.settings.max_response_bytes:
                        raise EnergyAPIError("energy API response exceeds configured limit")

                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > self.settings.max_response_bytes:
                            raise EnergyAPIError("energy API response exceeds configured limit")
                        chunks.append(chunk)
                    payload = json.loads(b"".join(chunks))
        except httpx.TimeoutException as exc:
            raise EnergyAPIError("energy API request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise EnergyAPIError(f"energy API returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EnergyAPIError("energy API request failed or returned invalid JSON") from exc
        return wrap_response(payload)

    @staticmethod
    def _query_params(query: EnergyQuery) -> dict[str, Any]:
        return query.model_dump(exclude_none=True)

    async def query_trend(self, query: EnergyQuery) -> dict[str, Any]:
        return await self._get(self.settings.trend_path, self._query_params(query))

    async def query_ranking(self, query: EnergyQuery) -> dict[str, Any]:
        return await self._get(self.settings.ranking_path, self._query_params(query))

    async def get_peak_value(self, query: EnergyQuery) -> dict[str, Any]:
        return await self._get(self.settings.peak_path, self._query_params(query))

    async def compare_period(self, query: EnergyCompareQuery) -> dict[str, Any]:
        return await self._get(self.settings.compare_path, self._query_params(query))

    async def get_alarm_summary(self, query: EnergyQuery) -> dict[str, Any]:
        return await self._get(self.settings.alarms_path, self._query_params(query))
