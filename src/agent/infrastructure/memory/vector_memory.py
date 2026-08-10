from typing import List, Optional

from src.agent.infrastructure.memory.embeddings import EmbeddingAdapter
from src.agent.infrastructure.memory.embeddings_factory import create_embedding_adapter
from src.agent.infrastructure.memory.vector_store import VectorStore


class VectorMemory:
    """向量记忆实现，基于嵌入向量和余弦检索。"""

    def __init__(self, adapter: EmbeddingAdapter = None):
        self._adapter = adapter or create_embedding_adapter()
        self._store = VectorStore(self._adapter)

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        self._store.add(text, metadata)

    def query(self, text: str, top_k: int = 3, user_id: Optional[str] = None) -> List[dict]:
        return self._store.query(text, top_k, user_id=user_id)

    def save(self, path: str) -> None:
        self._store.save(path)

    def load(self, path: str) -> None:
        self._store.load(path)
