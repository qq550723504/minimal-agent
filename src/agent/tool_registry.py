from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class ToolEntry:
    func: Callable[[str], str]
    description: str = ""


_TOOL_REGISTRY: Dict[str, ToolEntry] = {}


def register_tool(name: str, func: Callable[[str], str], description: str = "") -> None:
    """注册一个工具函数，用于执行器的工具步骤调用。"""
    _TOOL_REGISTRY[name.strip().lower()] = ToolEntry(func=func, description=description.strip())


def get_tool(name: str) -> Optional[Callable[[str], str]]:
    entry = _TOOL_REGISTRY.get(name.strip().lower())
    return entry.func if entry else None


def list_tools() -> List[str]:
    return sorted(_TOOL_REGISTRY.keys())


def list_tool_metadata() -> List[dict]:
    return [
        {"name": name, "description": entry.description}
        for name, entry in sorted(_TOOL_REGISTRY.items())
    ]


__all__ = ["register_tool", "get_tool", "list_tools", "list_tool_metadata"]
