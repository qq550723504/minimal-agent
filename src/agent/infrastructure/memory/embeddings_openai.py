import os
from typing import Any, List, Optional

from src.agent.infrastructure.memory.embeddings import EmbeddingAdapter


class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, model: str = "text-embedding-3-small", client: Optional[Any] = None):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai package is required for OpenAI embeddings") from e

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        self._client = client if client is not None else OpenAI(api_key=api_key)
        self._model = model

    def embed(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return resp.data[0].embedding
