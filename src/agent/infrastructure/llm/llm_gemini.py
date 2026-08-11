import json
import os
import re
from typing import Any, List, Optional

from src.agent.infrastructure.llm.llm import LLMAdapter, parse_plan_output


_STRUCTURED_PLAN_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "anyOf": [
            {"type": "string"},
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["tool_call"]},
                    "call_id": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["kind", "call_id", "tool", "arguments"],
            },
        ]
    },
}


def _response_schema_without_unsupported_fields(value: Any) -> Any:
    if isinstance(value, dict):
        supported = {
            "type",
            "properties",
            "required",
            "items",
            "enum",
            "anyOf",
            "description",
            "format",
            "pattern",
            "minLength",
            "maxLength",
            "minimum",
            "maximum",
        }
        result = {
            key: _response_schema_without_unsupported_fields(child)
            for key, child in value.items()
            if key in supported
        }
        if isinstance(value.get("properties"), dict):
            result["properties"] = {
                key: _response_schema_without_unsupported_fields(child)
                for key, child in value["properties"].items()
            }
        return result
    if isinstance(value, list):
        return [_response_schema_without_unsupported_fields(item) for item in value]
    return value


def _structured_plan_response_schema(prompt: str) -> dict[str, Any]:
    catalog_start = prompt.find("Tool catalog:")
    contract_start = prompt.find("Response contract:", catalog_start + 1)
    if catalog_start == -1 or contract_start == -1:
        return _STRUCTURED_PLAN_RESPONSE_SCHEMA

    catalog_text = prompt[catalog_start + len("Tool catalog:") : contract_start].strip()
    try:
        catalog = json.loads(catalog_text)
    except json.JSONDecodeError:
        return _STRUCTURED_PLAN_RESPONSE_SCHEMA
    if not isinstance(catalog, list):
        return _STRUCTURED_PLAN_RESPONSE_SCHEMA

    variants: list[dict[str, Any]] = []
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        tool_name = entry.get("name")
        input_schema = entry.get("input_schema")
        if not isinstance(tool_name, str) or not isinstance(input_schema, dict):
            continue
        arguments_schema = _response_schema_without_unsupported_fields(input_schema)
        if arguments_schema.get("type") != "object":
            continue
        variants.append(
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["tool_call"]},
                    "call_id": {"type": "string"},
                    "tool": {"type": "string", "enum": [tool_name]},
                    "arguments": arguments_schema,
                },
                "required": ["kind", "call_id", "tool", "arguments"],
            }
        )
    if not variants:
        return _STRUCTURED_PLAN_RESPONSE_SCHEMA
    return {"type": "array", "items": {"anyOf": [{"type": "string"}, *variants]}}


class GeminiAdapter(LLMAdapter):
    """Gemini 适配器。需要在环境变量 `GEMINI_API_KEY` 中提供 API key。"""

    def __init__(self, model: Optional[str] = None, client: Optional[Any] = None):
        try:
            from google import genai
        except Exception as e:
            raise RuntimeError("google-genai package is required for GeminiAdapter") from e

        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self._client = client if client is not None else genai.Client(api_key=self.api_key)
        self.model = model or "gemini-3.6-flash"

    def plan(self, prompt: str) -> List[Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "contents": prompt,
        }
        if "Response contract:" in prompt and "Return only a JSON array" in prompt:
            from google.genai import types

            request["config"] = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=_structured_plan_response_schema(prompt),
            )

        response = self._client.models.generate_content(**request)
        text = response.text
        if not text:
            return []
        parsed = parse_plan_output(text)
        if parsed:
            if all(isinstance(item, str) for item in parsed):
                return [item if item.startswith("echo: ") else f"echo: {item}" for item in parsed]
            return parsed

        parts = [p.strip() for p in re.split(r"[。.?!]", text) if p.strip()]
        return [f"echo: {p}" for p in parts]


__all__ = ["GeminiAdapter"]
