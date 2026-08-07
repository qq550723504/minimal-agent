from src.agent.config import LLM_BACKEND, OPENAI_MODEL
from src.agent.llm import MockLLM


def create_llm_adapter():
    backend = LLM_BACKEND
    if backend == "openai":
        from src.agent.llm_openai import OpenAIAdapter

        return OpenAIAdapter(model=OPENAI_MODEL)
    return MockLLM()
