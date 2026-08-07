import os


def _bool_env(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


LLM_BACKEND = os.getenv("AGENT_LLM_BACKEND", "mock").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
EMBEDDING_BACKEND = os.getenv("AGENT_EMBEDDING_BACKEND", "mock").strip().lower()
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip()
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2").strip()
VECTOR_MEMORY_PATH = os.getenv("VECTOR_MEMORY_PATH", "vector_memory.json").strip()
ENABLE_MEMORY = _bool_env("AGENT_ENABLE_MEMORY", "true")
QUEUE_WORKER_COUNT = int(os.getenv("QUEUE_WORKER_COUNT", "2"))
