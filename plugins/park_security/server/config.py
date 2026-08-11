from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_mode: Literal["mock"]
    approval_token: str | None = field(repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量读取服务地址、Mock 模式和人工审批凭证。"""
        data_mode = os.getenv("PARK_SECURITY_DATA_MODE", "mock").strip().lower()
        if data_mode != "mock":
            raise ValueError("PARK_SECURITY_DATA_MODE must be mock")

        approval_token = os.getenv("PARK_SECURITY_APPROVAL_TOKEN", "").strip() or None
        return cls(
            host=os.getenv("PARK_SECURITY_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("PARK_SECURITY_MCP_PORT", "8200")),
            data_mode="mock",
            approval_token=approval_token,
        )
