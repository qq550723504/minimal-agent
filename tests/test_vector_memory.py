import json
import tempfile
import pytest

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


def test_vector_memory_query_isolated_by_user():
    memory = VectorMemory()
    memory.add("shared project context", {"user_id": "alice"})
    memory.add("shared project context", {"user_id": "bob"})

    alice_results = memory.query("shared project", user_id="alice")
    bob_results = memory.query("shared project", user_id="bob")

    assert len(alice_results) == 1
    assert alice_results[0]["metadata"]["user_id"] == "alice"
    assert len(bob_results) == 1
    assert bob_results[0]["metadata"]["user_id"] == "bob"


def test_vector_memory_legacy_records_belong_to_default_user(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"documents": ["legacy context"], "metadata": [{}]}), encoding="utf-8")

    memory = VectorMemory()
    memory.load(str(path))

    assert memory.query("legacy", user_id="default")
    assert memory.query("legacy", user_id="alice") == []


def test_vector_memory_rejects_mismatched_persisted_lists(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps({"documents": ["one"], "metadata": [], "vectors": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="same length"):
        VectorMemory().load(str(path))


def test_vector_memory_save_creates_nested_parent(tmp_path):
    path = tmp_path / "nested" / "memory.json"
    memory = VectorMemory()
    memory.add("nested context")

    memory.save(str(path))

    assert path.exists()
