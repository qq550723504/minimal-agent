class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        embedding = type("Embedding", (), {"values": [0.1, 0.2, 0.3]})()
        return type("Response", (), {"embeddings": [embedding]})()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def test_gemini_embedding_adapter_uses_embed_content_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = FakeGeminiClient()

    from src.agent.embeddings_gemini import GeminiEmbeddingAdapter

    adapter = GeminiEmbeddingAdapter(model="gemini-embedding-test", client=client)

    assert adapter.embed("hello") == [0.1, 0.2, 0.3]
    assert client.models.calls == [
        {"model": "gemini-embedding-test", "contents": "hello"}
    ]
