from src.agent.config import (
    GEMINI_MODEL,
    LLM_BACKEND,
    OPENAI_MODEL,
    OPENAI_COMPATIBLE_API_KEY,
    OPENAI_COMPATIBLE_BASE_URL,
    OPENAI_COMPATIBLE_MODEL,
)
from src.agent.llm import MockLLM


def create_llm_adapter():
    backend = LLM_BACKEND
    if backend == "openai":
        from src.agent.llm_openai import OpenAIAdapter

        return OpenAIAdapter(model=OPENAI_MODEL)
    if backend == "gemini":
        from src.agent.llm_gemini import GeminiAdapter

        return GeminiAdapter(model=GEMINI_MODEL)
    if backend == "openai-compatible":
        from src.agent.llm_compatible import OpenAICompatibleAdapter

        return OpenAICompatibleAdapter(
            model=OPENAI_COMPATIBLE_MODEL,
            api_key_env="OPENAI_COMPATIBLE_API_KEY",
            base_url=OPENAI_COMPATIBLE_BASE_URL,
            max_retries=0,
        )
    if backend == "mock":
        return MockLLM()
    raise ValueError(f"Unsupported LLM backend: {backend}")
