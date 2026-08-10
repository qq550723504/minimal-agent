import json

import pytest

from src.agent.infrastructure.memory.embeddings import EmbeddingAdapter
from src.agent.infrastructure.memory.vector_store import VectorStore


class FailsOnSecondEmbedding(EmbeddingAdapter):
    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("embedding unavailable")
        return [float(self.calls)]


def test_failed_embedding_does_not_partially_append_vector_record(tmp_path):
    store = VectorStore(FailsOnSecondEmbedding())
    path = tmp_path / "vectors.json"

    store.add("first", {"user_id": "u1"})
    store.save(str(path))
    baseline = json.loads(path.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        store.add("second", {"user_id": "u1"})

    store.save(str(path))
    assert json.loads(path.read_text(encoding="utf-8")) == baseline


def test_embedding_calls_happen_outside_vector_store_lock():
    store = None

    class LockAwareEmbedding(EmbeddingAdapter):
        def embed(self, text):
            assert not store._lock._is_owned()
            return [1.0]

    store = VectorStore(LockAwareEmbedding())
    store.add("first")
    store.query("first")
