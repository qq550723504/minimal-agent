from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    api_token: str | None
    token_header: str
    token_prefix: str
    timeout_seconds: float
    max_response_bytes: int
    trend_path: str
    ranking_path: str
    peak_path: str
    compare_path: str
    alarms_path: str
    host: str
    port: int
    data_mode: Literal["rest", "mock"]
    project_ids: tuple[int, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        data_mode = os.getenv("PARK_ENERGY_DATA_MODE", "rest").strip().lower()
        if data_mode not in {"rest", "mock"}:
            raise ValueError("PARK_ENERGY_DATA_MODE must be rest or mock")

        return cls(
            api_base_url=os.getenv("ENERGY_API_BASE_URL", "http://localhost:9000").rstrip("/"),
            api_token=os.getenv("ENERGY_API_TOKEN") or None,
            token_header=os.getenv("ENERGY_API_TOKEN_HEADER", "Authorization"),
            token_prefix=os.getenv("ENERGY_API_TOKEN_PREFIX", "Bearer"),
            timeout_seconds=_float_env("ENERGY_API_TIMEOUT_SECONDS", 10.0),
            max_response_bytes=int(os.getenv("ENERGY_API_MAX_RESPONSE_BYTES", "1048576")),
            trend_path=os.getenv("ENERGY_TREND_PATH", "/api/agent/v1/energy/trend"),
            ranking_path=os.getenv("ENERGY_RANKING_PATH", "/api/agent/v1/energy/ranking"),
            peak_path=os.getenv("ENERGY_PEAK_PATH", "/api/energy/peak"),
            compare_path=os.getenv("ENERGY_COMPARE_PATH", "/api/agent/v1/energy/compare"),
            alarms_path=os.getenv("ENERGY_ALARMS_PATH", "/api/agent/v1/energy/anomalies"),
            host=os.getenv("PARK_ENERGY_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("PARK_ENERGY_MCP_PORT", "8100")),
            data_mode=data_mode,
            project_ids=tuple(
                int(value.strip())
                for value in os.getenv("ENERGY_PROJECT_IDS", "").split(",")
                if value.strip()
            ),
        )
