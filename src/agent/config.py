import math
import os


def _bool_env(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _has_configured_api_key() -> bool:
    for item in os.getenv("AGENT_API_KEYS", "").split(","):
        if ":" not in item:
            continue
        user_id, key = (part.strip() for part in item.split(":", 1))
        if user_id and user_id != "default" and key:
            return True
    return False


LLM_BACKEND = os.getenv("AGENT_LLM_BACKEND", "mock").strip().lower()
DEPLOYMENT_MODE = os.getenv("AGENT_DEPLOYMENT_MODE", "development").strip().lower()
CAPABILITY_RUNTIME_ENABLED = _bool_env("AGENT_CAPABILITY_RUNTIME_ENABLED", "false")
PLUGIN_DIR = os.getenv("AGENT_PLUGIN_DIR", "plugins").strip()
MCP_ALLOWED_HOSTS = _csv_env("AGENT_MCP_ALLOWED_HOSTS")
MCP_STDIO_ALLOWED_COMMANDS = _csv_env("AGENT_MCP_STDIO_ALLOWED_COMMANDS")
MCP_STARTUP_TIMEOUT_SECONDS = float(os.getenv("AGENT_MCP_STARTUP_TIMEOUT_SECONDS", "30"))
MCP_DISCOVERY_TIMEOUT_SECONDS = float(os.getenv("AGENT_MCP_DISCOVERY_TIMEOUT_SECONDS", "30"))
MCP_SHUTDOWN_TIMEOUT_SECONDS = float(os.getenv("AGENT_MCP_SHUTDOWN_TIMEOUT_SECONDS", "10"))
MAX_ACTIVE_SKILLS = int(os.getenv("AGENT_MAX_ACTIVE_SKILLS", "3"))
MAX_SKILL_REFERENCE_BYTES = int(os.getenv("AGENT_MAX_SKILL_REFERENCE_BYTES", "262144"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
EMBEDDING_BACKEND = os.getenv("AGENT_EMBEDDING_BACKEND", "mock").strip().lower()
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small").strip()
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2").strip()
VECTOR_MEMORY_PATH = os.getenv("VECTOR_MEMORY_PATH", "vector_memory.json").strip()
ENABLE_MEMORY = _bool_env("AGENT_ENABLE_MEMORY", "true")
QUEUE_WORKER_COUNT = int(os.getenv("QUEUE_WORKER_COUNT", "2"))
WORKFLOW_STORE_PATH = os.getenv("WORKFLOW_STORE_PATH", "data/workflows.sqlite3").strip()
MAX_TOOL_RESULT_BYTES = int(os.getenv("AGENT_MAX_TOOL_RESULT_BYTES", "1048576"))
if MAX_TOOL_RESULT_BYTES <= 0:
    raise ValueError("AGENT_MAX_TOOL_RESULT_BYTES must be positive")
if MAX_ACTIVE_SKILLS <= 0:
    raise ValueError("AGENT_MAX_ACTIVE_SKILLS must be positive")
if MAX_SKILL_REFERENCE_BYTES <= 0:
    raise ValueError("AGENT_MAX_SKILL_REFERENCE_BYTES must be positive")
if any(
    not math.isfinite(value) or value <= 0
    for value in (
        MCP_STARTUP_TIMEOUT_SECONDS,
        MCP_DISCOVERY_TIMEOUT_SECONDS,
        MCP_SHUTDOWN_TIMEOUT_SECONDS,
    )
):
    raise ValueError("MCP lifecycle timeouts must be finite and positive")
if DEPLOYMENT_MODE not in {"development", "production"}:
    raise ValueError("AGENT_DEPLOYMENT_MODE must be development or production")
if DEPLOYMENT_MODE == "production":
    if not _bool_env("AGENT_AUTH_REQUIRED", "false"):
        raise ValueError("AGENT_AUTH_REQUIRED must be true in production")
    if not _has_configured_api_key():
        raise ValueError("AGENT_API_KEYS must contain a non-default user key in production")
    metrics_api_key = os.getenv("AGENT_METRICS_API_KEY", "").strip()
    if not metrics_api_key or metrics_api_key == "local-dev-metrics":
        raise ValueError("AGENT_METRICS_API_KEY must be a non-default value in production")
    if not _csv_env("AGENT_HTTP_ALLOWED_HOSTS"):
        raise ValueError("AGENT_HTTP_ALLOWED_HOSTS must be configured in production")
