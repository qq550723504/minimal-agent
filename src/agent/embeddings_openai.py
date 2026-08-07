import os
from typing import List

from src.agent.embeddings import EmbeddingAdapter


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, model: str = "text-embedding-3-small"):
        try:
            import openai
        except ImportError as e:
            raise RuntimeError("openai package is required for OpenAI embeddings") from e

        self._openai = openai
        self._openai.api_key = os.getenv("OPENAI_API_KEY")
        if not self._openai.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        self._model = model

    def embed(self, text: str) -> List[float]:
        resp = self._openai.embeddings.create(
            model=self._model,
            input=text,
        )
        return resp["data"][0]["embedding"]
