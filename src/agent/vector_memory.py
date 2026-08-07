from typing import List, Optional

from src.agent.embeddings import EmbeddingAdapter
from src.agent.embeddings_factory import create_embedding_adapter
from src.agent.vector_store import VectorStore


class VectorMemory:
    """向量记忆实现，基于嵌入向量和余弦检索。"""

    def __init__(self, adapter: EmbeddingAdapter = None):
        self._adapter = adapter or create_embedding_adapter()
        self._store = VectorStore(self._adapter)

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        self._store.add(text, metadata)

    def query(self, text: str, top_k: int = 3) -> List[dict]:
        return self._store.query(text, top_k)

    def save(self, path: str) -> None:
        self._store.save(path)

    def load(self, path: str) -> None:
        self._store.load(path)
