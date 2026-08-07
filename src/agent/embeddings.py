from abc import ABC, abstractmethod
from typing import List


class EmbeddingAdapter(ABC):
    """Embedding 适配器接口。"""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        raise NotImplementedError()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]


class MockEmbeddingAdapter(EmbeddingAdapter):
    """本地模拟 embedding，便于无 API key 时测试。"""

    def embed(self, text: str) -> List[float]:
        normalized = text.lower()
        vector = [0.0] * 26
        for ch in normalized:
            if "a" <= ch <= "z":
                vector[ord(ch) - ord("a")] += 1.0
        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]


__all__ = ["EmbeddingAdapter", "MockEmbeddingAdapter"]