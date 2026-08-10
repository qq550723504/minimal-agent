import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.infrastructure.memory.vector_memory import VectorMemory

_vector_memory = VectorMemory()
_initialized = False


def _is_memory_enabled() -> bool:
    return os.getenv("AGENT_ENABLE_MEMORY", "true").strip().lower() in ("1", "true", "yes", "on")


def is_memory_enabled() -> bool:
    return _is_memory_enabled()


def _get_memory_path() -> str:
    return os.getenv("VECTOR_MEMORY_PATH", "vector_memory.json")


def initialize_memory() -> None:
    global _initialized
    if not is_memory_enabled() or _initialized:
        return

    path = Path(_get_memory_path())
    if path.exists():
        _vector_memory.load(str(path))
    _initialized = True


def save_memory() -> None:
    if not is_memory_enabled() or not _initialized:
        return
    _vector_memory.save(_get_memory_path())


def add_memory(text: str, metadata: Optional[dict] = None) -> None:
    if not is_memory_enabled():
        return
    _vector_memory.add(text, metadata)


def get_relevant_memory(text: str, top_k: int = 3, user_id: str = "default") -> List[Dict[str, Any]]:
    if not is_memory_enabled():
        return []
    return _vector_memory.query(text, top_k=top_k, user_id=user_id)


def reset_memory() -> None:
    global _initialized, _vector_memory
    _initialized = False
    _vector_memory = VectorMemory()
