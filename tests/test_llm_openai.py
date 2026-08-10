class FakeChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": "第一句。第二句?"})()},
                    )
                ]
            },
        )()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


def test_openai_adapter_uses_v1_chat_client_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    client = FakeOpenAIClient()

    from src.agent.infrastructure.llm.llm_openai import OpenAIAdapter

    adapter = OpenAIAdapter(model="dummy-model", client=client)

    assert adapter.plan("任何提示") == ["echo: 第一句", "echo: 第二句"]
    assert client.chat.completions.calls == [
        {
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "任何提示"}],
            "max_tokens": 512,
        }
    ]
