import os
import re
from typing import Any, List, Optional

from src.agent.llm import LLMAdapter, parse_plan_output


class OpenAICompatibleAdapter(LLMAdapter):
    """Adapter for providers exposing the OpenAI Chat Completions contract."""

    def __init__(
        self,
        model: str,
        api_key_env: str,
        base_url: Optional[str] = None,
        client: Optional[Any] = None,
    ):
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError(
                "openai package is required for OpenAI-compatible adapters"
            ) from exc

        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env)
        if not self.api_key:
            raise ValueError(f"{api_key_env} is not set")
        if base_url is not None and not base_url.strip():
            raise ValueError("base_url is not set")
        self.base_url = base_url
        if client is not None:
            self._client = client
        else:
            client_kwargs = {"api_key": self.api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            self._client = OpenAI(**client_kwargs)
        self.model = model

    def plan(self, prompt: str) -> List[Any]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        text = response.choices[0].message.content
        if not text:
            return []
        parsed = parse_plan_output(text)
        if parsed:
            return [
                item
                if not isinstance(item, str) or item.startswith("echo: ")
                else f"echo: {item}"
                for item in parsed
            ]

        parts = [p.strip() for p in re.split(r"[。？！?!]", text) if p.strip()]
        return [f"echo: {p}" for p in parts]


__all__ = ["OpenAICompatibleAdapter"]
