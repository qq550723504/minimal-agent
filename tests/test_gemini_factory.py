def test_create_llm_adapter_selects_gemini(monkeypatch):
    import src.agent.llm_factory as factory

    monkeypatch.setattr(factory, "LLM_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_MODEL", "gemini-test", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    assert factory.create_llm_adapter().__class__.__name__ == "GeminiAdapter"


def test_create_embedding_adapter_selects_gemini(monkeypatch):
    import src.agent.embeddings_factory as factory

    monkeypatch.setattr(factory, "EMBEDDING_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-test", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    assert factory.create_embedding_adapter().__class__.__name__ == "GeminiEmbeddingAdapter"
