"""Secure configuration boundaries for MCP client transports."""

from .security import (
    MCPSecurityError,
    ResolvedHTTPConfig,
    ResolvedStdioConfig,
    validate_http_config,
    validate_stdio_config,
)

__all__ = [
    "MCPSecurityError",
    "ResolvedHTTPConfig",
    "ResolvedStdioConfig",
    "validate_http_config",
    "validate_stdio_config",
]
