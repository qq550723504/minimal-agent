def test_create_llm_adapter_selects_gemini(monkeypatch):
    import src.agent.llm_factory as factory

    monkeypatch.setattr(factory, "LLM_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_MODEL", "gemini-test", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    assert factory.create_llm_adapter().__class__.__name__ == "GeminiAdapter"


def test_create_llm_adapter_rejects_removed_qwen_backend(monkeypatch):
    import src.agent.llm_factory as factory

    monkeypatch.setattr(factory, "LLM_BACKEND", "qwen")

    try:
        factory.create_llm_adapter()
    except ValueError as exc:
        assert str(exc) == "Unsupported LLM backend: qwen"
    else:
        raise AssertionError("expected removed qwen backend to fail explicitly")


def test_create_llm_adapter_selects_generic_openai_compatible_backend(monkeypatch):
    import src.agent.llm_factory as factory

    monkeypatch.setattr(factory, "LLM_BACKEND", "openai-compatible")
    monkeypatch.setattr(factory, "OPENAI_COMPATIBLE_MODEL", "provider-model", raising=False)
    monkeypatch.setattr(factory, "OPENAI_COMPATIBLE_BASE_URL", "https://provider.test/v1", raising=False)
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "provider-key")

    adapter = factory.create_llm_adapter()

    assert adapter.__class__.__name__ == "OpenAICompatibleAdapter"
    assert adapter.model == "provider-model"
    assert adapter.api_key_env == "OPENAI_COMPATIBLE_API_KEY"
    assert adapter.base_url == "https://provider.test/v1"


def test_create_embedding_adapter_selects_gemini(monkeypatch):
    import src.agent.embeddings_factory as factory

    monkeypatch.setattr(factory, "EMBEDDING_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-test", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    assert factory.create_embedding_adapter().__class__.__name__ == "GeminiEmbeddingAdapter"
