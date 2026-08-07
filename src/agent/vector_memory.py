from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class VectorMemory:
    """一个最小的文本向量记忆实现，基于 TF-IDF 向量和余弦相似度。"""

    def __init__(self):
        self._documents: List[str] = []
        self._metadata: List[dict] = []
        self._vectorizer = TfidfVectorizer()
        self._matrix = None

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        metadata = metadata or {}
        self._documents.append(text)
        self._metadata.append(metadata)
        self._matrix = self._vectorizer.fit_transform(self._documents)

    def query(self, text: str, top_k: int = 3) -> List[dict]:
        if not self._documents:
            return []
        query_vec = self._vectorizer.transform([text])
        similarities = cosine_similarity(query_vec, self._matrix)[0]
        top_idx = similarities.argsort()[::-1][:top_k]
        return [
            {"text": self._documents[i], "score": float(similarities[i]), "metadata": self._metadata[i]}
            for i in top_idx
        ]
