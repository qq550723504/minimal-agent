from src.agent.config import (
    DASHSCOPE_BASE_URL,
    GEMINI_MODEL,
    LLM_BACKEND,
    OPENAI_MODEL,
    QWEN_MODEL,
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
    if backend == "qwen":
        from src.agent.llm_compatible import OpenAICompatibleAdapter

        return OpenAICompatibleAdapter(
            model=QWEN_MODEL,
            api_key_env="DASHSCOPE_API_KEY",
            base_url=DASHSCOPE_BASE_URL,
        )
    return MockLLM()
