"""Official SDK transport factories with DNS-rebinding-safe HTTP pinning."""

from __future__ import annotations

from typing import Any, AsyncContextManager
from urllib.parse import urlsplit

import httpx2
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

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
    ) -> None:
        if not config.addresses:
            raise ValueError("mcp_http_dns_failed")
        self._config = config
        self._address = config.addresses[0]
        self._delegate = delegate or httpx2.AsyncHTTPTransport(
            trust_env=False,
            http1=True,
            http2=True,
        )
        parsed = urlsplit(config.url)
        default_port = 443 if parsed.scheme == "https" else 80
        self._host_header = (
            config.hostname
            if config.port == default_port
            else f"{config.hostname}:{config.port}"
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Pin the origin while leaving framing, pooling, and streaming to httpx2."""
        if (
            request.url.scheme != urlsplit(self._config.url).scheme
            or request.url.host != self._config.hostname
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
        pinned_request = httpx2.Request(
            request.method,
            request.url.copy_with(host=self._address),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._delegate.handle_async_request(pinned_request)

    async def aclose(self) -> None:
        await self._delegate.aclose()


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return {"http": 80, "https": 443}.get(scheme)
