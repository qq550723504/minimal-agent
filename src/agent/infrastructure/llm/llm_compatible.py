import json
import os
import re
from typing import Any, List, Optional

from src.agent.infrastructure.llm.llm import LLMAdapter, parse_plan_output


class OpenAICompatibleAdapter(LLMAdapter):
    """Adapter for providers exposing the OpenAI Chat Completions contract."""

    def __init__(
        self,
        model: str,
        api_key_env: str,
        base_url: Optional[str] = None,
        client: Optional[Any] = None,
        max_retries: Optional[int] = None,
    ):
        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError(
                "openai package is required for OpenAI-compatible adapters"
            ) from exc

        self.api_key_env = api_key_env
        self.api_key = os.getenv(api_key_env, "").strip()
        if not self.api_key:
            raise ValueError(f"{api_key_env} is not set")
        self.model = model.strip()
        if not self.model:
            raise ValueError("model is not set")
        if base_url is not None and not base_url.strip():
            raise ValueError("base_url is not set")
        self.base_url = base_url
        self.max_retries = max_retries
        if client is not None:
            self._client = client
        else:
            client_kwargs = {"api_key": self.api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            if max_retries is not None:
                client_kwargs["max_retries"] = max_retries
            self._client = OpenAI(**client_kwargs)

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
        try:
            if isinstance(json.loads(text.strip()), list):
                return []
        except json.JSONDecodeError:
            pass

        parts = [p.strip() for p in re.split(r"[。？！?!]", text) if p.strip()]
        return [f"echo: {p}" for p in parts]


__all__ = ["OpenAICompatibleAdapter"]
