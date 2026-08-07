import os
import re
from typing import Any, List, Optional

from src.agent.llm import LLMAdapter, parse_plan_output


class GeminiAdapter(LLMAdapter):
    """Gemini 适配器。需要在环境变量 `GEMINI_API_KEY` 中提供 API key。"""

    def __init__(self, model: Optional[str] = None, client: Optional[Any] = None):
        try:
            from google import genai
        except Exception as e:
            raise RuntimeError("google-genai package is required for GeminiAdapter") from e

        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        self._client = client if client is not None else genai.Client(api_key=self.api_key)
        self.model = model or "gemini-2.5-flash"

    def plan(self, prompt: str) -> List[Any]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        text = response.text
        if not text:
            return []
        parsed = parse_plan_output(text)
        if parsed:
            if all(isinstance(item, str) for item in parsed):
                return [item if item.startswith("echo: ") else f"echo: {item}" for item in parsed]
            return parsed

        parts = [p.strip() for p in re.split(r"[。.?!]", text) if p.strip()]
        return [f"echo: {p}" for p in parts]


__all__ = ["GeminiAdapter"]
