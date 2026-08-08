"""Official SDK transport factories with DNS-rebinding-safe HTTP pinning."""

from __future__ import annotations

import ipaddress
from typing import Any, AsyncContextManager
from urllib.parse import urlsplit

import httpx2
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from src.agent.config import MAX_TOOL_RESULT_BYTES

from .security import ResolvedHTTPConfig, ResolvedStdioConfig


def stdio_transport(config: ResolvedStdioConfig) -> AsyncContextManager[Any]:
    """Create the SDK stdio transport from an already validated configuration."""
    parameters = StdioServerParameters(
        command=str(config.command),
        args=list(config.args),
        env=dict(config.env),
        cwd=str(config.cwd),
    )
    return stdio_client(parameters)


def http_transport(
    config: ResolvedHTTPConfig, http_client: httpx2.AsyncClient
) -> AsyncContextManager[Any]:
    """Create the SDK Streamable HTTP transport using the pinned HTTP client."""
    return streamable_http_client(
        config.url,
        http_client=http_client,
        terminate_on_close=True,
    )


class PinnedHostAsyncTransport(httpx2.AsyncBaseTransport):
    """Delegate HTTP to httpx2 while connecting only to validated IP addresses."""

    def __init__(
        self,
        config: ResolvedHTTPConfig,
        *,
        delegate: httpx2.AsyncBaseTransport | None = None,
        max_response_bytes: int = MAX_TOOL_RESULT_BYTES,
    ) -> None:
        if not config.addresses:
            raise ValueError("mcp_http_dns_failed")
        self._config = config
        self._addresses = tuple(config.addresses)
        self._max_response_bytes = max_response_bytes
        self._scheme = urlsplit(config.url).scheme
        self._delegate = delegate or httpx2.AsyncHTTPTransport(
            trust_env=False,
            http1=True,
            http2=True,
        )
        default_port = 443 if self._scheme == "https" else 80
        parsed_hostname = urlsplit(config.url).hostname
        host = _format_host(config.hostname)
        if parsed_hostname and parsed_hostname.endswith(".") and not host.startswith("["):
            host = f"{host}."
        self._host_header = (
            host
            if config.port == default_port
            else f"{host}:{config.port}"
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Pin the origin while leaving framing, pooling, and streaming to httpx2."""
        if (
            request.url.scheme != self._scheme
            or _normalize_hostname(request.url.host) != self._config.hostname
            or _effective_port(request.url.scheme, request.url.port) != self._config.port
        ):
            raise httpx2.RequestError("mcp_http_pinned_origin_required", request=request)

        headers = [
            (name, value)
            for name, value in request.headers.multi_items()
            if name.lower() != "host"
        ]
        headers.append(("Host", self._host_header))
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self._config.hostname
        last_error: httpx2.RequestError | None = None
        for address in self._addresses:
            pinned_request = httpx2.Request(
                request.method,
                request.url.copy_with(host=address),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            try:
                response = await self._delegate.handle_async_request(pinned_request)
                content_length = response.headers.get("content-length")
                if content_length is not None and int(content_length) > self._max_response_bytes:
                    await response.aclose()
                    raise MCPResponseTooLarge("mcp_response_too_large")
                if isinstance(response.stream, httpx2.AsyncByteStream):
                    response.stream = _BoundedAsyncByteStream(
                        response.stream, self._max_response_bytes
                    )
                return response
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as error:
                last_error = error
        assert last_error is not None
        raise last_error

    async def aclose(self) -> None:
        await self._delegate.aclose()


class MCPResponseTooLarge(RuntimeError):
    """Raised when an MCP HTTP response exceeds the global result limit."""


class _BoundedAsyncByteStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._total = 0

    async def __aiter__(self):
        async for chunk in self._stream:
            self._total += len(chunk)
            if self._total > self._limit:
                raise MCPResponseTooLarge("mcp_response_too_large")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return {"http": 80, "https": 443}.get(scheme)


def _format_host(hostname: str) -> str:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return f"[{address}]" if address.version == 6 else str(address)


def _normalize_hostname(hostname: str) -> str:
    try:
        return str(ipaddress.ip_address(hostname))
    except ValueError:
        return hostname.rstrip(".").lower().encode("idna").decode("ascii")
