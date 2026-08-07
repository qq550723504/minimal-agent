import os

import openai


def test_openai_adapter_monkeypatch(monkeypatch):
    # 模拟环境变量
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")

    # 模拟 openai.ChatCompletion.create 的返回值
    def fake_create(model, messages, max_tokens):
        return {"choices": [{"message": {"content": "第一句。第二句?"}}]}

    # 有些 openai 发行版没有 ChatCompletion 属性，模拟整个 ChatCompletion 类
    monkeypatch.setattr(openai, "ChatCompletion", type("C", (), {"create": staticmethod(fake_create)}), raising=False)

    from src.agent.llm_openai import OpenAIAdapter

    adapter = OpenAIAdapter(model="dummy-model")
    steps = adapter.plan("任何提示")
    assert steps == ["echo: 第一句", "echo: 第二句"]
