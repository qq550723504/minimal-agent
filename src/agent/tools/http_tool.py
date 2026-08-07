import json
import os
from typing import Any

from src.agent.http_security import pin_dns_resolution, validate_http_url


def _timeout() -> tuple[float, float]:
    try:
        seconds = float(os.getenv("AGENT_HTTP_TIMEOUT_SECONDS", "5"))
    except ValueError as exc:
        raise ValueError("AGENT_HTTP_TIMEOUT_SECONDS must be a number") from exc
    if seconds <= 0:
        raise ValueError("AGENT_HTTP_TIMEOUT_SECONDS must be positive")
    return seconds, seconds


def _max_response_bytes() -> int:
    try:
        limit = int(os.getenv("AGENT_HTTP_MAX_RESPONSE_BYTES", "1048576"))
    except ValueError as exc:
        raise ValueError("AGENT_HTTP_MAX_RESPONSE_BYTES must be an integer") from exc
    if limit <= 0:
        raise ValueError("AGENT_HTTP_MAX_RESPONSE_BYTES must be positive")
    return limit


def _read_json_response(response: Any, max_bytes: int) -> dict:
    if 300 <= response.status_code < 400:
        raise ValueError("HTTP redirects are not allowed")
    response.raise_for_status()

    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise ValueError("HTTP response is too large")
        except ValueError as exc:
            if str(exc) == "HTTP response is too large":
                raise
            raise ValueError("HTTP response Content-Length is invalid") from exc

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=min(8192, max_bytes)):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("HTTP response is too large")
        chunks.append(chunk)

    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("HTTP response is not valid JSON") from exc


def call_http_get(url: str, params: dict | None = None) -> dict:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required for HTTP tools") from exc

    parsed = validate_http_url(url)
    with pin_dns_resolution(parsed):
        response = requests.get(
            parsed.url,
            params=params,
            timeout=_timeout(),
            allow_redirects=False,
            stream=True,
        )
    return _read_json_response(response, _max_response_bytes())


def call_http_post(url: str, data: dict | None = None, json_body: dict | None = None) -> dict:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required for HTTP tools") from exc

    parsed = validate_http_url(url)
    with pin_dns_resolution(parsed):
        response = requests.post(
            parsed.url,
            data=data,
            json=json_body,
            timeout=_timeout(),
            allow_redirects=False,
            stream=True,
        )
    return _read_json_response(response, _max_response_bytes())
