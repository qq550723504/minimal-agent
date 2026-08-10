class FakeChatCompletions:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self.text})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class FakeClient:
    def __init__(self, text):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions(text)})()


def test_compatible_adapter_uses_chat_contract(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy-key")
    client = FakeClient("first. second.")

    from src.agent.llm_compatible import OpenAICompatibleAdapter

    adapter = OpenAICompatibleAdapter(
        model="qwen-test",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.test/v1",
        client=client,
    )

    assert adapter.plan("prompt") == ["echo: first", "echo: second"]
    assert client.chat.completions.calls == [
        {
            "model": "qwen-test",
            "messages": [{"role": "user", "content": "prompt"}],
            "max_tokens": 512,
        }
    ]


def test_compatible_adapter_returns_empty_plan_without_text(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy-key")

    from src.agent.llm_compatible import OpenAICompatibleAdapter

    adapter = OpenAICompatibleAdapter(
        model="qwen-test",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.test/v1",
        client=FakeClient(None),
    )

    assert adapter.plan("prompt") == []


def test_compatible_adapter_configures_openai_client_base_url(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy-key")
    created = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)

    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    from src.agent.llm_compatible import OpenAICompatibleAdapter

    OpenAICompatibleAdapter(
        model="qwen-test",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.test/v1",
    )

    assert created == [
        {"api_key": "dummy-key", "base_url": "https://dashscope.test/v1"}
    ]


def test_compatible_adapter_requires_configured_api_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    from src.agent.llm_compatible import OpenAICompatibleAdapter

    try:
        OpenAICompatibleAdapter(
            model="qwen-test",
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://dashscope.test/v1",
            client=FakeClient("ignored"),
        )
    except ValueError as exc:
        assert str(exc) == "DASHSCOPE_API_KEY is not set"
    else:
        raise AssertionError("expected missing API key to fail")
