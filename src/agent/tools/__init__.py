import json

from src.agent.tool_registry import register_tool
from src.agent.tools.http_tool import call_http_get, call_http_post


def _http_get_tool(payload: str) -> str:
    if payload.startswith("{"):
        spec = json.loads(payload)
        url = spec.get("url")
        params = spec.get("params")
    else:
        url = payload
        params = None

    result = call_http_get(url, params=params)
    if not isinstance(result, str):
        return json.dumps(result, ensure_ascii=False)
    return result


def _http_post_tool(payload: str) -> str:
    if payload.startswith("{"):
        spec = json.loads(payload)
        url = spec.get("url")
        data = spec.get("data")
        json_body = spec.get("json")
    else:
        raise ValueError("http_post requires a JSON payload with url and data or json")

    result = call_http_post(url, data=data, json_body=json_body)
    if not isinstance(result, str):
        return json.dumps(result, ensure_ascii=False)
    return result

register_tool(
    "http_get",
    _http_get_tool,
    description="Send an HTTP GET request with optional query parameters.",
)
register_tool(
    "http_post",
    _http_post_tool,
    description="Send an HTTP POST request with optional data or JSON body.",
)

__all__ = ["call_http_get", "call_http_post", "_http_get_tool", "_http_post_tool"]
