import os
import socket
import sys
from pathlib import Path

import pytest

from src.agent.mcp.security import (
    MCPSecurityError,
    validate_http_config,
    validate_stdio_config,
)
from src.agent.plugins.models import HTTPMCPServerManifest, StdioMCPServerManifest


def _tool() -> list[dict[str, object]]:
    return [{"name": "echo", "side_effects": False, "idempotent": True}]


@pytest.fixture
def stdio_manifest() -> StdioMCPServerManifest:
    return StdioMCPServerManifest(
        id="local",
        transport="stdio",
        command=sys.executable,
        args=["-m", "demo"],
        allowed_tools=_tool(),
    )


@pytest.fixture
def http_manifest() -> HTTPMCPServerManifest:
    return HTTPMCPServerManifest(
        id="remote",
        transport="streamable_http",
        url_env="DEMO_URL",
        headers_env={"Authorization": "DEMO_TOKEN"},
        allowed_tools=_tool(),
    )


@pytest.mark.parametrize("command", ["cmd", "powershell", "pwsh", "bash", "sh"])
def test_stdio_rejects_shell_wrappers(command, stdio_manifest, tmp_path):
    """A shell wrapper would turn structured arguments into executable code."""
    stdio_manifest.command = command

    with pytest.raises(MCPSecurityError, match="mcp_stdio_shell_forbidden"):
        validate_stdio_config(stdio_manifest, tmp_path, {command})


@pytest.mark.parametrize("extension", [".cmd", ".bat"])
def test_stdio_rejects_allowlisted_windows_batch_wrapper(
    extension, stdio_manifest, tmp_path
):
    """An allowlisted batch file still invokes cmd.exe and is therefore a shell wrapper."""
    wrapper = tmp_path / f"server{extension}"
    wrapper.write_text("@echo off\r\n", encoding="utf-8")
    stdio_manifest.command = str(wrapper)

    with pytest.raises(MCPSecurityError, match="mcp_stdio_shell_forbidden"):
        validate_stdio_config(stdio_manifest, tmp_path, {str(wrapper)})


def test_stdio_resolves_allowed_executable_and_only_declared_environment(
    stdio_manifest, tmp_path
):
    """Changing the allowlist or leaking an undeclared secret must break this."""
    stdio_manifest.cwd = "."
    stdio_manifest.env_vars = {"CHILD_TOKEN": "HOST_TOKEN"}
    environment = {"HOST_TOKEN": "token", "UNDECLARED_SECRET": "do-not-leak"}

    resolved = validate_stdio_config(
        stdio_manifest, tmp_path, {sys.executable}, environ=environment
    )

    assert resolved.command == Path(sys.executable).resolve()
    assert resolved.cwd == tmp_path.resolve()
    assert resolved.env["CHILD_TOKEN"] == "token"
    assert "UNDECLARED_SECRET" not in resolved.env


def test_stdio_rejects_command_not_in_exact_absolute_allowlist(stdio_manifest, tmp_path):
    """A different executable must not pass because only its filename is similar."""
    similarly_named_executable = tmp_path / Path(sys.executable).name
    similarly_named_executable.write_text("not an executable", encoding="utf-8")

    with pytest.raises(MCPSecurityError, match="mcp_stdio_command_forbidden"):
        validate_stdio_config(stdio_manifest, tmp_path, {str(similarly_named_executable)})


def test_stdio_rejects_cwd_outside_plugin_root(stdio_manifest, tmp_path):
    """An escaping cwd could expose files outside the installed plugin."""
    stdio_manifest.cwd = ".."

    with pytest.raises(MCPSecurityError, match="mcp_stdio_cwd_forbidden"):
        validate_stdio_config(stdio_manifest, tmp_path, {sys.executable})


def test_http_requires_exact_allowed_https_host(http_manifest, monkeypatch):
    """Production must reject plain HTTP before making a DNS request."""
    monkeypatch.setenv("DEMO_URL", "http://169.254.169.254/mcp")

    with pytest.raises(MCPSecurityError, match="mcp_http_https_required"):
        validate_http_config(http_manifest, os.environ, {"mcp.example.com"}, production=True)


def test_http_normalizes_host_and_retains_all_validated_addresses(
    http_manifest, monkeypatch
):
    """Dropping an address would make later DNS pinning incomplete."""
    monkeypatch.setenv("DEMO_URL", "https://MCP.example.com./mcp")
    monkeypatch.setenv("DEMO_TOKEN", "Bearer test-token")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        ],
    )

    resolved = validate_http_config(
        http_manifest,
        os.environ,
        {"mcp.example.com"},
        production=True,
    )

    assert resolved.hostname == "mcp.example.com"
    assert resolved.addresses == ("1.1.1.1", "8.8.8.8")
    assert resolved.headers == {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.1.1", "0.0.0.0"],
)
def test_http_rejects_every_unsafe_resolved_address(http_manifest, monkeypatch, address):
    """One unsafe DNS answer must reject the whole connection target."""
    monkeypatch.setenv("DEMO_URL", "https://mcp.example.com/mcp")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)),
        ],
    )

    with pytest.raises(MCPSecurityError, match="mcp_http_unsafe_address"):
        validate_http_config(http_manifest, os.environ, {"mcp.example.com"}, production=True)


def test_http_dev_override_allows_non_global_loopback(http_manifest, monkeypatch):
    monkeypatch.setenv("DEMO_URL", "http://127.0.0.1/mcp")
    monkeypatch.setenv("DEMO_TOKEN", "test")

    resolved = validate_http_config(
        http_manifest, os.environ, {"127.0.0.1"}, production=False
    )

    assert resolved.addresses == ("127.0.0.1",)


@pytest.mark.parametrize("url", ["https://user:pass@mcp.example.com", "https://mcp.example.com/#fragment"])
def test_http_rejects_credentials_and_fragments(http_manifest, monkeypatch, url):
    """URLs containing credentials or fragments must never reach a transport."""
    monkeypatch.setenv("DEMO_URL", url)

    with pytest.raises(MCPSecurityError, match="mcp_http_url_forbidden"):
        validate_http_config(http_manifest, os.environ, {"mcp.example.com"}, production=True)
