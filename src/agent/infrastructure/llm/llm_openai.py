from typing import Any, Optional

from src.agent.infrastructure.llm.llm_compatible import OpenAICompatibleAdapter


class OpenAIAdapter(OpenAICompatibleAdapter):
    """OpenAI adapter using the shared OpenAI-compatible implementation."""

    def __init__(self, model: Optional[str] = None, client: Optional[Any] = None):
        super().__init__(
            model=model or "gpt-3.5-turbo",
            api_key_env="OPENAI_API_KEY",
            client=client,
        )


__all__ = ["OpenAIAdapter"]
