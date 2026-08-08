"""Strict contracts for administrator-provided plugin manifests."""

import math
from collections.abc import Iterable
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


_IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"
_SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    path: str
    triggers: list[str] = Field(default_factory=list)

    @field_validator("triggers", mode="after")
    @classmethod
    def normalize_triggers(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            trigger = " ".join(value.casefold().strip().split())
            if trigger and trigger not in seen:
                normalized.append(trigger)
                seen.add(trigger)
        return normalized


class AllowedToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    side_effects: bool
    idempotent: bool
    timeout_seconds: float = Field(default=30.0, gt=0)
    result_size_limit: int = Field(default=1_048_576, gt=0)

    @field_validator("timeout_seconds")
    @classmethod
    def reject_non_finite_timeout(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timeout_seconds must be finite")
        return value


class StdioMCPServerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    transport: Literal["stdio"]
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[AllowedToolManifest]

    @model_validator(mode="after")
    def reject_duplicate_allowed_tool_names(self) -> "StdioMCPServerManifest":
        _reject_duplicates(
            (tool.name for tool in self.allowed_tools), "duplicate allowed tool name"
        )
        return self


class HTTPMCPServerManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    transport: Literal["streamable_http"]
    url_env: str
    headers_env: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[AllowedToolManifest]

    @model_validator(mode="after")
    def reject_duplicate_allowed_tool_names(self) -> "HTTPMCPServerManifest":
        _reject_duplicates(
            (tool.name for tool in self.allowed_tools), "duplicate allowed tool name"
        )
        return self


MCPServerManifest: TypeAlias = Annotated[
    StdioMCPServerManifest | HTTPMCPServerManifest,
    Field(discriminator="transport"),
]


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["minimal-agent/v1"]
    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: str = Field(pattern=_SEMVER_PATTERN)
    enabled: StrictBool = True
    required: StrictBool = False
    skills: list[SkillManifest] = Field(default_factory=list)
    mcp_servers: list[MCPServerManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_declarations(self) -> "PluginManifest":
        _reject_duplicates((skill.id for skill in self.skills), "duplicate skill id")
        _reject_duplicates(
            (trigger for skill in self.skills for trigger in skill.triggers),
            "duplicate skill trigger",
        )
        _reject_duplicates(
            (server.id for server in self.mcp_servers), "duplicate MCP server id"
        )
        return self


def _reject_duplicates(values: Iterable[str], message: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(message)
        seen.add(value)
