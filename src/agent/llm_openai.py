import json
import os
import re
from typing import Any, List, Optional

from src.agent.llm import LLMAdapter, parse_plan_output


class OpenAIAdapter(LLMAdapter):
    """OpenAI 适配器。需要在环境变量 `OPENAI_API_KEY` 中提供 API key。"""

    def __init__(self, model: Optional[str] = None):
        try:
            import openai
        except Exception as e:
            raise RuntimeError("openai package is required for OpenAIAdapter") from e

        self._openai = openai
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        self._openai.api_key = self.api_key
        self.model = model or "gpt-3.5-turbo"

    def plan(self, prompt: str) -> List[Any]:
        resp = self._openai.ChatCompletion.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        text = resp["choices"][0]["message"]["content"]
        parsed = parse_plan_output(text)
        if parsed:
            return parsed

        parts = [p.strip() for p in re.split(r"[。.?!]", text) if p.strip()]
        return [f"echo: {p}" for p in parts]


__all__ = ["OpenAIAdapter"]
