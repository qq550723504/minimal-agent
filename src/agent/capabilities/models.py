from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolSource(StrEnum):
    LOCAL = "local"
    PLUGIN = "plugin"
    MCP = "mcp"


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    description: str = ""
    input_schema: dict[str, Any]
    source: ToolSource
    plugin_id: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    side_effects: bool
    idempotent: bool
    result_size_limit: int = Field(default=1_048_576, gt=0)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1, max_length=128)
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationContext(BaseModel):
    owner_id: str = "default"
    run_id: str | None = None
    active_skill_ids: tuple[str, ...] = ()


class ToolResult(BaseModel):
    call_id: str
    tool: str
    status: ToolResultStatus
    content: Any = None
    error_code: str | None = None
    retryable: bool = False
