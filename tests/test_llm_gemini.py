class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"text": "第一句。第二句?"})()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def test_gemini_adapter_uses_generate_content_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = FakeGeminiClient()

    from src.agent.llm_gemini import GeminiAdapter

    adapter = GeminiAdapter(model="gemini-test", client=client)

    assert adapter.plan("任何提示") == ["echo: 第一句", "echo: 第二句"]
    assert client.models.calls == [
        {"model": "gemini-test", "contents": "任何提示"}
    ]
