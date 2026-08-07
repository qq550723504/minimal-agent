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

    assert loaded.query("hello")[0]["text"] == "hello world"
    assert loaded.query("another")[0]["text"] == "another document"
    assert loaded._metadata[0]["source"] == "test"
    assert loaded._metadata[1]["source"] == "test2"
