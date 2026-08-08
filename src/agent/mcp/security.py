"""Validation boundaries for administrator-declared MCP transports."""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from mcp.client.stdio import get_default_environment

from src.agent.plugins.models import HTTPMCPServerManifest, StdioMCPServerManifest


class MCPSecurityError(ValueError):
    """A stable, secret-free code for an MCP transport policy violation."""


@dataclass(frozen=True)
class ResolvedStdioConfig:
    command: Path
    args: tuple[str, ...]
    cwd: Path
    env: dict[str, str]


@dataclass(frozen=True)
class ResolvedHTTPConfig:
    url: str
    hostname: str
    port: int
    headers: dict[str, str]
    addresses: tuple[str, ...]


_SHELL_BASENAMES = frozenset({"cmd", "powershell", "pwsh", "bash", "sh"})
_SHELL_EXTENSIONS = frozenset({".bat", ".cmd"})


def validate_stdio_config(
    server: StdioMCPServerManifest,
    plugin_root: Path,
    allowed_commands: Set[str],
    environ: Mapping[str, str] | None = None,
) -> ResolvedStdioConfig:
    """Resolve a stdio command without granting shell or host-env access."""
    if _shell_name(server.command):
        raise MCPSecurityError("mcp_stdio_shell_forbidden")
    command = _resolve_command(server.command, "mcp_stdio_command_invalid")
    if _shell_basename(command):
        raise MCPSecurityError("mcp_stdio_shell_forbidden")

    permitted = {
        _normalize_path(_resolve_command(value, "mcp_stdio_command_invalid"))
        for value in allowed_commands
    }
    if _normalize_path(command) not in permitted:
        raise MCPSecurityError("mcp_stdio_command_forbidden")

    cwd = _resolve_cwd(plugin_root, server.cwd)
    host_environment = os.environ if environ is None else environ
    environment = get_default_environment()
    for child_name, host_name in server.env_vars.items():
        value = host_environment.get(host_name)
        if value is None:
            raise MCPSecurityError("mcp_stdio_env_missing")
        environment[child_name] = value

    return ResolvedStdioConfig(command, tuple(server.args), cwd, environment)


def validate_http_config(
    server: HTTPMCPServerManifest,
    environ: Mapping[str, str],
    allowed_hosts: Set[str],
    production: bool,
) -> ResolvedHTTPConfig:
    """Resolve and validate a Streamable HTTP target before any connection."""
    url = environ.get(server.url_env)
    if not isinstance(url, str) or not url.strip():
        raise MCPSecurityError("mcp_http_url_missing")

    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise MCPSecurityError("mcp_http_url_forbidden") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.fragment:
        raise MCPSecurityError("mcp_http_url_forbidden")
    if production and scheme != "https":
        raise MCPSecurityError("mcp_http_https_required")
    if not parsed.hostname:
        raise MCPSecurityError("mcp_http_url_forbidden")

    hostname = _normalize_hostname(parsed.hostname)
    permitted_hosts = {_normalize_hostname(host) for host in allowed_hosts if host.strip()}
    if hostname not in permitted_hosts:
        raise MCPSecurityError("mcp_http_host_forbidden")

    resolved_port = port if port is not None else (443 if scheme == "https" else 80)
    addresses = _resolve_addresses(hostname, resolved_port)
    if production and any(_unsafe_address(address) for address in addresses):
        raise MCPSecurityError("mcp_http_unsafe_address")

    headers: dict[str, str] = {}
    for header_name, environment_name in server.headers_env.items():
        value = environ.get(environment_name)
        if value is None:
            raise MCPSecurityError("mcp_http_header_missing")
        headers[header_name] = value

    return ResolvedHTTPConfig(
        url=url.strip(),
        hostname=hostname,
        port=resolved_port,
        headers=headers,
        addresses=tuple(sorted({str(address) for address in addresses})),
    )


def _resolve_command(command: str, error_code: str) -> Path:
    if not isinstance(command, str) or not command.strip():
        raise MCPSecurityError(error_code)
    candidate = Path(command)
    try:
        if candidate.is_absolute():
            return candidate.resolve(strict=True)
        located = shutil.which(command)
        if located:
            return Path(located).resolve(strict=True)
    except OSError as error:
        raise MCPSecurityError(error_code) from error
    raise MCPSecurityError(error_code)


def _resolve_cwd(plugin_root: Path, cwd: str | None) -> Path:
    try:
        root = plugin_root.resolve(strict=True)
        candidate = root if cwd is None else (root / Path(cwd)).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise MCPSecurityError("mcp_stdio_cwd_forbidden") from error
    if not candidate.is_dir():
        raise MCPSecurityError("mcp_stdio_cwd_forbidden")
    return candidate


def _resolve_addresses(hostname: str, port: int) -> tuple[ipaddress._BaseAddress, ...]:
    try:
        literal = ipaddress.ip_address(hostname)
        return (literal,)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = tuple(ipaddress.ip_address(info[4][0]) for info in infos)
    except (OSError, ValueError) as error:
        raise MCPSecurityError("mcp_http_dns_failed") from error
    if not addresses:
        raise MCPSecurityError("mcp_http_dns_failed")
    return addresses


def _unsafe_address(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _normalize_hostname(hostname: str) -> str:
    return hostname.rstrip(".").lower().encode("idna").decode("ascii")


def _normalize_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _shell_basename(command: Path) -> bool:
    return command.suffix.lower() in _SHELL_EXTENSIONS or _shell_name(command.name)


def _shell_name(command: str) -> bool:
    name = Path(command).name.lower()
    return name.rsplit(".", 1)[0] in _SHELL_BASENAMES
