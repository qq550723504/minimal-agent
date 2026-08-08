"""Strict contracts for administrator-provided plugin manifests."""

from collections.abc import Iterable
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


_IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    path: str
    triggers: list[str] = Field(default_factory=list)


class AllowedToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    side_effects: bool
    idempotent: bool
    timeout_seconds: float = Field(default=30.0, gt=0)
    result_size_limit: int = Field(default=1_048_576, gt=0)


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
    version: str
    enabled: bool = True
    required: bool = False
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
