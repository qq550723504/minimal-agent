import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.embeddings import EmbeddingAdapter


class VectorStore:
    def __init__(self, embedding_adapter: EmbeddingAdapter):
        self._adapter = embedding_adapter
        self._documents: List[str] = []
        self._metadata: List[dict] = []
        self._vectors: List[List[float]] = []
        self._lock = threading.RLock()

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        vector = self._adapter.embed(text)
        with self._lock:
            self._documents.append(text)
            self._metadata.append(metadata or {})
            self._vectors.append(vector)

    def query(self, text: str, top_k: int = 3, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query_vector = self._adapter.embed(text)
        with self._lock:
            if not self._documents:
                return []
            scored = []
            for index, (document, metadata, vector) in enumerate(zip(self._documents, self._metadata, self._vectors)):
                owner_id = metadata.get("user_id", "default")
                if user_id is not None and owner_id != user_id:
                    continue
                score = self._cosine_similarity(query_vector, vector)
                if score > 0:
                    scored.append({"text": document, "score": score, "metadata": metadata})
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored[:top_k]

    def save(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = {
                "documents": self._documents,
                "metadata": self._metadata,
                "vectors": self._vectors,
            }
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    json.dump(data, temporary, ensure_ascii=False, indent=2)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, target)
            finally:
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink()

    def load(self, path: str) -> None:
        try:
            raw = Path(path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid vector memory file: {path}") from exc

        documents = data.get("documents") if isinstance(data, dict) else None
        metadata = data.get("metadata") if isinstance(data, dict) else None
        vectors = data.get("vectors") if isinstance(data, dict) else None
        if not isinstance(documents, list) or not all(isinstance(item, str) for item in documents):
            raise ValueError("vector memory documents must be a list of strings")
        if metadata is None:
            metadata = [{} for _ in documents]
        if not isinstance(metadata, list) or len(metadata) != len(documents):
            raise ValueError("vector memory documents and metadata must have the same length")
        if not all(isinstance(item, dict) for item in metadata):
            raise ValueError("vector memory metadata must be a list of objects")
        if vectors is None:
            vectors = []
        if not isinstance(vectors, list):
            raise ValueError("vector memory vectors must be a list")
        if vectors and len(vectors) != len(documents):
            raise ValueError("vector memory documents and vectors must have the same length")
        if vectors and not all(isinstance(vector, list) and all(isinstance(value, (int, float)) for value in vector) for vector in vectors):
            raise ValueError("vector memory vectors must be numeric lists")
        if not vectors:
            vectors = [self._adapter.embed(text) for text in documents]

        with self._lock:
            self._documents = documents
            self._metadata = metadata
            self._vectors = vectors

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


__all__ = ["VectorStore"]
