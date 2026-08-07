import os
from typing import Any, List, Optional

from src.agent.embeddings import EmbeddingAdapter


class GeminiEmbeddingAdapter(EmbeddingAdapter):
    """Gemini Embeddings 适配器。需要 `GEMINI_API_KEY`。"""

    def __init__(self, model: str = "gemini-embedding-2", client: Optional[Any] = None):
        try:
            from google import genai
        except ImportError as e:
            raise RuntimeError("google-genai package is required for Gemini embeddings") from e

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for Gemini embeddings")
        self._client = client if client is not None else genai.Client(api_key=api_key)
        self._model = model

    def embed(self, text: str) -> List[float]:
        response = self._client.models.embed_content(
            model=self._model,
            contents=text,
        )
        return response.embeddings[0].values


__all__ = ["GeminiEmbeddingAdapter"]
