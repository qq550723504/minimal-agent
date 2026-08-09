import json
import re
from typing import Any, List, Optional, Sequence

from src.agent.capabilities.models import ToolSpec
from src.agent import config
from src.agent.llm import LLMAdapter
from src.agent.llm_factory import create_llm_adapter
from src.agent.memory import get_global_memory
from src.agent.memory_manager import add_memory, get_relevant_memory, initialize_memory, is_memory_enabled
from src.agent.plan_models import coerce_plan_items
from src.agent.tool_registry import get_capability_registry


_SAFE_TOOL_FIELDS = ("name", "description", "input_schema", "side_effects", "idempotent")
_SAFE_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "oneOf",
    "anyOf",
    "allOf",
}
_REDACTED_SCHEMA_VALUE = "[REDACTED]"
_SENSITIVE_NAME_PATTERNS = (
    re.compile(r"(^|[_-])(api[_-]?key|token|secret|password|credential|headers?[_-]?env|env)([_-]|$)", re.IGNORECASE),
)
_URL_FRAGMENT_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_ENV_NAME_FRAGMENT_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
_COMMAND_FRAGMENT_PATTERN = re.compile(
    r"(?:(?<=^)|(?<=[\s(]))(?:curl|wget|bash|sh|pwsh|powershell|cmd(?:\.exe)?|python(?:\d+(?:\.\d+)*)?|pip|uv|npm|yarn|pnpm|node|docker|kubectl|git|make)(?:\s+[^\s,;]+){1,6}",
    re.IGNORECASE,
)
_ENV_VALUE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(^|[_-])(api[_-]?key|token|secret|password|credential)([_-]|$)", re.IGNORECASE),
    re.compile(r"^sk-[A-Za-z0-9_-]+$"),
    re.compile(r"^Bearer\s+\S+$", re.IGNORECASE),
)
_CREDENTIAL_FRAGMENT_PATTERNS = (
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"\b(?:api[_-]?key|token|secret|password|credential)[-_][A-Za-z0-9._~+/=-]+\b", re.IGNORECASE),
    re.compile(r"\b(?:api(?:\s+|[_-])?key|token|password|credential)\s+[A-Za-z0-9._~+/=-]+\b", re.IGNORECASE),
)
_COMMAND_VALUE_PATTERN = re.compile(
    r"^\s*(?:curl|wget|bash|sh|pwsh|powershell|cmd(?:\.exe)?|python(?:\d+(?:\.\d+)*)?|pip|uv|npm|yarn|pnpm|node|docker|kubectl|git|make)\b",
    re.IGNORECASE,
)
STRUCTURED_TOOL_CALLING_ENABLED: bool | None = None


def _format_conversation_history(conversation_history: List[dict]) -> str:
    history_lines = [f"- {item.get('prompt', '')}" for item in conversation_history if item.get("prompt")]
    return "Conversation history:\n" + "\n".join(history_lines) if history_lines else ""


def _structured_tool_calling_enabled() -> bool:
    override = STRUCTURED_TOOL_CALLING_ENABLED
    if isinstance(override, bool):
        return override
    return config.STRUCTURED_TOOL_CALLING_ENABLED


def _format_relevant_memory(memories: List[dict]) -> str:
    memory_lines = [
        f"- {item['text']}" + (
            f" (source={item['metadata'].get('source')})" if item.get('metadata') and item['metadata'].get('source') else ""
        )
        for item in memories
    ]
    return "Relevant memory:\n" + "\n".join(memory_lines) if memory_lines else ""


def _sanitize_input_schema(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        sanitized_properties: dict[str, Any] = {}
        raw_properties = value.get("properties")
        if isinstance(raw_properties, dict):
            for property_name, property_schema in sorted(raw_properties.items()):
                if not isinstance(property_schema, dict) or _is_sensitive_schema_name(property_name):
                    continue
                sanitized_properties[property_name] = _sanitize_input_schema(property_schema)
        for key, child in value.items():
            if key not in _SAFE_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(child, dict):
                sanitized[key] = sanitized_properties
                continue
            if key in {"oneOf", "anyOf", "allOf"} and isinstance(child, list):
                sanitized[key] = [_sanitize_input_schema(item) for item in child if isinstance(item, dict)]
                continue
            if key == "items":
                sanitized[key] = _sanitize_input_schema(child)
                continue
            if key == "additionalProperties":
                if isinstance(child, dict):
                    sanitized[key] = _sanitize_input_schema(child)
                    continue
                if isinstance(child, bool):
                    sanitized[key] = child
                    continue
            if key == "required" and isinstance(child, list):
                sanitized[key] = [
                    item for item in child
                    if isinstance(item, str) and not _is_sensitive_schema_name(item) and item in sanitized_properties
                ]
                continue
            if key == "enum" and isinstance(child, list):
                sanitized[key] = [_sanitize_scalar(item) for item in child]
                continue
            if key == "const":
                sanitized[key] = _sanitize_scalar(child)
                continue
            sanitized[key] = child
        return sanitized
    if isinstance(value, list):
        return [_sanitize_input_schema(item) for item in value if isinstance(item, (dict, list))]
    return value


def _sanitize_catalog_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_catalog_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_catalog_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text_fragments(value)
    return value


def _is_sensitive_schema_name(name: str) -> bool:
    return any(pattern.search(name) for pattern in _SENSITIVE_NAME_PATTERNS)


def _sanitize_text_fragments(value: str) -> str:
    sanitized = value
    for pattern in (_URL_FRAGMENT_PATTERN, _COMMAND_FRAGMENT_PATTERN, _ENV_NAME_FRAGMENT_PATTERN):
        sanitized = pattern.sub(_REDACTED_SCHEMA_VALUE, sanitized)
    for pattern in _CREDENTIAL_FRAGMENT_PATTERNS:
        sanitized = pattern.sub(_REDACTED_SCHEMA_VALUE, sanitized)
    return sanitized


def _sanitize_scalar(value: Any) -> Any:
    if isinstance(value, str) and _is_sensitive_scalar(value):
        return _REDACTED_SCHEMA_VALUE
    return value


def _is_sensitive_scalar(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if "://" in stripped:
        return True
    if _COMMAND_VALUE_PATTERN.match(stripped):
        return True
    if _ENV_VALUE_PATTERN.fullmatch(stripped):
        return True
    return any(pattern.search(stripped) for pattern in _CREDENTIAL_VALUE_PATTERNS)


def build_tool_catalog_prompt(specs: Sequence[ToolSpec]) -> str:
    catalog = []
    for spec in sorted(specs, key=lambda item: item.name):
        entry = {}
        for field_name in _SAFE_TOOL_FIELDS:
            value = getattr(spec, field_name)
            if field_name == "input_schema":
                value = _sanitize_input_schema(value)
            entry[field_name] = _sanitize_catalog_value(value)
        catalog.append(entry)

    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "Tool catalog:\n"
        f"{catalog_json}\n\n"
        "Response contract:\n"
        "Return only a JSON array.\n"
        "Each array item must be either a plain string step or a tool call object with this exact shape:\n"
        '{ "kind": "tool_call", "call_id": "call-1", "tool": "tool.name", "arguments": {"...": "..."} }\n'
        "Do not return markdown."
    )


def _build_rag_prompt(
    prompt: str,
    memories: List[dict],
    conversation_history: Optional[List[dict]] = None,
    tool_catalog_prompt: str = "",
) -> str:
    if not memories and not conversation_history and not tool_catalog_prompt:
        return prompt

    sections = []
    if conversation_history:
        history_section = _format_conversation_history(conversation_history)
        if history_section:
            sections.append(history_section)

    if memories:
        memory_section = _format_relevant_memory(memories)
        if memory_section:
            sections.append(memory_section)

    context_block = "\n\n".join(sections)
    if tool_catalog_prompt:
        context_block = "\n\n".join(part for part in [context_block, tool_catalog_prompt] if part)

    response_format = (
        "Return only the JSON array contract above."
        if tool_catalog_prompt
        else "Provide each step on a separate line without markdown bullets."
    )
    return (
        "System:\n"
        "You are an AI planning assistant. Use the provided context to produce an actionable plan. "
        "If the context is not relevant, prioritize the task description.\n\n"
        f"{context_block}\n\n"
        "Task:\n"
        f"{prompt}\n\n"
        "Response format:\n"
        f"{response_format}"
    )


def plan_task(
    prompt: str,
    user_id: str = "default",
    llm: Optional[LLMAdapter] = None,
    *,
    tool_specs: Optional[Sequence[ToolSpec]] = None,
    structured_tools: Optional[bool] = None,
) -> List[Any]:
    """将输入转换为待执行步骤；支持注入 LLMAdapter（若为空则使用默认行为）。"""
    if is_memory_enabled():
        initialize_memory()

    mem = get_global_memory()
    conversation_history: List[dict] = []
    if user_id != "default":
        conversation_history = mem.recent(user_id, limit=5)

    structured_mode = _structured_tool_calling_enabled() if structured_tools is None else structured_tools

    wrapped_prompt = prompt
    relevant: List[dict] = []
    if is_memory_enabled():
        relevant = get_relevant_memory(prompt, top_k=3, user_id=user_id)

    tool_catalog_prompt = ""
    if structured_mode:
        effective_tool_specs = list(tool_specs) if tool_specs is not None else get_capability_registry().list_specs()
        tool_catalog_prompt = build_tool_catalog_prompt(effective_tool_specs)

    if relevant or conversation_history or structured_mode:
        wrapped_prompt = _build_rag_prompt(prompt, relevant, conversation_history, tool_catalog_prompt)

    if user_id != "default":
        mem.add(user_id, {"prompt": prompt})

    if is_memory_enabled():
        add_memory(prompt, {"user_id": user_id})

    if llm is None:
        llm = create_llm_adapter()

    plan = llm.plan(wrapped_prompt)
    if structured_mode:
        return coerce_plan_items(plan)
    return plan


def build_plan_summary(steps: List[str]) -> str:
    return "; ".join(steps)
