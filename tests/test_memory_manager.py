from pathlib import Path

from src.agent.memory_manager import initialize_memory, save_memory, add_memory, reset_memory
from src.agent.vector_memory import VectorMemory


def test_memory_manager_save_load(tmp_path, monkeypatch):
    path = tmp_path / "vector_memory.json"
    monkeypatch.setenv("VECTOR_MEMORY_PATH", str(path))
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "true")

    reset_memory()
    initialize_memory()
    add_memory("hello world", {"source": "test"})
    add_memory("another doc", {"source": "test2"})
    save_memory()

    loaded = VectorMemory()
    loaded.load(str(path))

    results_hello = loaded.query("hello")
    results_another = loaded.query("another")

    assert any(item["text"] == "hello world" for item in results_hello)
    assert any(item["text"] == "another doc" for item in results_another)


def test_memory_manager_filters_relevant_memory_by_user(monkeypatch):
    from src.agent.memory_manager import get_relevant_memory

    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "true")
    reset_memory()
    initialize_memory()
    add_memory("shared context", {"user_id": "alice"})
    add_memory("shared context", {"user_id": "bob"})

    results = get_relevant_memory("shared context", user_id="alice")

    assert results
    assert all(item["metadata"].get("user_id") == "alice" for item in results)
