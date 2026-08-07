from src.agent.config import GEMINI_MODEL, LLM_BACKEND, OPENAI_MODEL
from src.agent.llm import MockLLM


def create_llm_adapter():
    backend = LLM_BACKEND
    if backend == "openai":
        from src.agent.llm_openai import OpenAIAdapter

        return OpenAIAdapter(model=OPENAI_MODEL)
    if backend == "gemini":
        from src.agent.llm_gemini import GeminiAdapter

        return GeminiAdapter(model=GEMINI_MODEL)
    return MockLLM()
