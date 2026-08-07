import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.config import ENABLE_MEMORY
from src.agent.vector_memory import VectorMemory

_vector_memory = VectorMemory()
_initialized = False


def _is_memory_enabled() -> bool:
    return os.getenv("AGENT_ENABLE_MEMORY", "true").strip().lower() in ("1", "true", "yes", "on")


def _get_memory_path() -> str:
    return os.getenv("VECTOR_MEMORY_PATH", "vector_memory.json")


def initialize_memory() -> None:
    global _initialized
    if not ENABLE_MEMORY or not _is_memory_enabled() or _initialized:
        return

    path = Path(_get_memory_path())
    if path.exists():
        _vector_memory.load(str(path))
    _initialized = True


def save_memory() -> None:
    if not ENABLE_MEMORY or not _is_memory_enabled() or not _initialized:
        return
    _vector_memory.save(_get_memory_path())


def add_memory(text: str, metadata: Optional[dict] = None) -> None:
    if not ENABLE_MEMORY or not _is_memory_enabled():
        return
    _vector_memory.add(text, metadata)


def get_relevant_memory(text: str, top_k: int = 3) -> List[Dict[str, Any]]:
    if not ENABLE_MEMORY or not _is_memory_enabled():
        return []
    return _vector_memory.query(text, top_k=top_k)


def reset_memory() -> None:
    global _initialized, _vector_memory
    _initialized = False
    _vector_memory = VectorMemory()
