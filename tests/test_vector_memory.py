import json
import tempfile

from src.agent.vector_memory import VectorMemory


def test_vector_memory_save_and_load(tmp_path):
    memory = VectorMemory()
    memory.add("hello world", {"source": "test"})
    memory.add("another document", {"source": "test2"})

    file_path = tmp_path / "memory.json"
    memory.save(str(file_path))

    loaded = VectorMemory()
    loaded.load(str(file_path))

    hello_results = loaded.query("hello")
    another_results = loaded.query("another")

    assert any(item["text"] == "hello world" for item in hello_results)
    assert any(item["text"] == "another document" for item in another_results)
    assert any(item["metadata"].get("source") == "test" for item in hello_results)
    assert any(item["metadata"].get("source") == "test2" for item in another_results)
