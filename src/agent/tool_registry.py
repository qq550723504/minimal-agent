import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from src.agent.domain.capabilities.models import ToolSource, ToolSpec
from src.agent.domain.capabilities.registry import CapabilityRegistry


@dataclass
class ToolEntry:
    func: Callable[[str], str]
    description: str = ""


_TOOL_REGISTRY: Dict[str, ToolEntry] = {}
CAPABILITY_REGISTRY = CapabilityRegistry()
_CAPABILITY_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def register_tool(name: str, func: Callable[[str], str], description: str = "") -> None:
    """注册一个工具函数，用于执行器的工具步骤调用。"""
    normalized_name = name.strip().lower()
    normalized_description = description.strip()

    if _CAPABILITY_NAME_PATTERN.fullmatch(normalized_name):
        async def legacy_handler(arguments, _context):
            return func(arguments.get("payload", ""))

        CAPABILITY_REGISTRY.register(
            ToolSpec(
                name=normalized_name,
                description=normalized_description,
                input_schema={
                    "type": "object",
                    "properties": {"payload": {"type": "string"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
                source=ToolSource.LOCAL,
                side_effects=True,
                idempotent=False,
            ),
            legacy_handler,
            replace=True,
        )

    _TOOL_REGISTRY[normalized_name] = ToolEntry(
        func=func,
        description=normalized_description,
    )


def get_capability_registry() -> CapabilityRegistry:
    return CAPABILITY_REGISTRY


def get_tool(name: str) -> Optional[Callable[[str], str]]:
    entry = _TOOL_REGISTRY.get(name.strip().lower())
    return entry.func if entry else None


def list_tools() -> List[str]:
    return sorted(set(_TOOL_REGISTRY) | {spec.name for spec in CAPABILITY_REGISTRY.list_specs()})


def list_tool_metadata() -> List[dict]:
    structured = {
        spec.name: {
            "name": spec.name,
            "description": spec.description,
            "source": spec.source.value,
            "plugin_id": spec.plugin_id,
            "input_schema": spec.input_schema,
            "side_effects": spec.side_effects,
            "idempotent": spec.idempotent,
        }
        for spec in CAPABILITY_REGISTRY.list_specs()
    }
    for name, entry in _TOOL_REGISTRY.items():
        structured.setdefault(
            name,
            {
                "name": name,
                "description": entry.description,
                "source": ToolSource.LOCAL.value,
                "plugin_id": None,
                "input_schema": {
                    "type": "object",
                    "properties": {"payload": {"type": "string"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
                "side_effects": True,
                "idempotent": False,
            },
        )
    return [structured[name] for name in sorted(structured)]


__all__ = [
    "register_tool",
    "get_tool",
    "list_tools",
    "list_tool_metadata",
    "get_capability_registry",
]
