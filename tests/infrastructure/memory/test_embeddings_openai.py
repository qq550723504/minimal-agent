class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {"data": [type("EmbeddingData", (), {"embedding": [0.1, 0.2, 0.3]})()]},
        )()


class FakeOpenAIClient:
    def __init__(self):
        self.embeddings = FakeEmbeddings()


def test_openai_embedding_adapter_uses_v1_embeddings_client_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    client = FakeOpenAIClient()

    from src.agent.infrastructure.memory.embeddings_openai import OpenAIEmbeddingAdapter

    adapter = OpenAIEmbeddingAdapter(model="dummy-embedding", client=client)

    assert adapter.embed("hello") == [0.1, 0.2, 0.3]
    assert client.embeddings.calls == [
        {"model": "dummy-embedding", "input": "hello"}
    ]
