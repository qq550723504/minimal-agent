from src.agent.config import EMBEDDING_BACKEND, OPENAI_EMBEDDING_MODEL
from src.agent.embeddings import MockEmbeddingAdapter


def create_embedding_adapter():
    backend = EMBEDDING_BACKEND
    if backend == "openai":
        try:
            from src.agent.embeddings_openai import OpenAIEmbeddingAdapter
        except ImportError as exc:
            raise RuntimeError("openai package is required for OpenAI embeddings") from exc
        return OpenAIEmbeddingAdapter(model=OPENAI_EMBEDDING_MODEL)
    return MockEmbeddingAdapter()
