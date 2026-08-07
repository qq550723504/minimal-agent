from src.agent.config import EMBEDDING_BACKEND, GEMINI_EMBEDDING_MODEL, OPENAI_EMBEDDING_MODEL
from src.agent.embeddings import MockEmbeddingAdapter


def create_embedding_adapter():
    backend = EMBEDDING_BACKEND
    if backend == "openai":
        try:
            from src.agent.embeddings_openai import OpenAIEmbeddingAdapter
        except ImportError as exc:
            raise RuntimeError("openai package is required for OpenAI embeddings") from exc
        return OpenAIEmbeddingAdapter(model=OPENAI_EMBEDDING_MODEL)
    if backend == "gemini":
        try:
            from src.agent.embeddings_gemini import GeminiEmbeddingAdapter
        except ImportError as exc:
            raise RuntimeError("google-genai package is required for Gemini embeddings") from exc
        return GeminiEmbeddingAdapter(model=GEMINI_EMBEDDING_MODEL)
    return MockEmbeddingAdapter()
