import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.embeddings import EmbeddingAdapter


class VectorStore:
    def __init__(self, embedding_adapter: EmbeddingAdapter):
        self._adapter = embedding_adapter
        self._documents: List[str] = []
        self._metadata: List[dict] = []
        self._vectors: List[List[float]] = []

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        metadata = metadata or {}
        self._documents.append(text)
        self._metadata.append(metadata)
        self._vectors.append(self._adapter.embed(text))

    def query(self, text: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self._documents:
            return []
        query_vector = self._adapter.embed(text)
        similarities = [self._cosine_similarity(query_vector, vec) for vec in self._vectors]
        scored = [
            {"text": self._documents[i], "score": similarities[i], "metadata": self._metadata[i]}
            for i in sorted(range(len(similarities)), key=lambda ix: similarities[ix], reverse=True)
            if similarities[i] > 0
        ]
        return scored[:top_k]

    def save(self, path: str) -> None:
        data = {
            "documents": self._documents,
            "metadata": self._metadata,
            "vectors": self._vectors,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str) -> None:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        self._documents = data.get("documents", [])
        self._metadata = data.get("metadata", [])
        self._vectors = data.get("vectors", [])

        # Migrate legacy persisted format when vectors are missing or mismatched.
        if len(self._vectors) != len(self._documents):
            self._vectors = [self._adapter.embed(text) for text in self._documents]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


__all__ = ["VectorStore"]
