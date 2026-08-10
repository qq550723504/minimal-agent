import os
from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).parents[1]

_CONFIG_ENVIRONMENT_KEYS = {
    "AGENT_DEPLOYMENT_MODE",
    "AGENT_AUTH_REQUIRED",
    "AGENT_API_KEYS",
    "AGENT_METRICS_API_KEY",
    "AGENT_HTTP_ALLOWED_HOSTS",
}

_COMPOSE_ENV_INTERPOLATION = re.compile(r"^\$\{(?P<name>[^}:]+)(?::-(?P<default>.*))?\}$")


def _import_config_with_environment(**values):
    environment = os.environ.copy()
    for key in _CONFIG_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    environment.update(values)
    return subprocess.run(
        [sys.executable, "-c", "import src.agent.config"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _load_agent_compose_environment() -> dict[str, str]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    return compose["services"]["agent"]["environment"]


def _compose_default(name: str) -> str | None:
    value = _load_agent_compose_environment()[name]
    match = _COMPOSE_ENV_INTERPOLATION.fullmatch(value)
    assert match, f"unexpected compose environment expression for {name}: {value!r}"
    return match.group("default")


def test_prometheus_config_is_tracked_and_compose_references_it():
    prometheus_path = ROOT / "prometheus.yml"
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert prometheus_path.exists()
    assert "./prometheus.yml:/etc/prometheus/prometheus.yml:ro" in compose
    assert (ROOT / "data" / "metrics-token").exists()
    assert "./data:/etc/prometheus/data:ro" in compose
    prometheus = prometheus_path.read_text(encoding="utf-8")
    assert "credentials_file" in prometheus
    assert "    authorization:" in prometheus
    assert "    http_config:" not in prometheus


def test_ci_does_not_hide_dependency_install_failures():
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        content = workflow.read_text(encoding="utf-8")
        assert "pip install -r requirements.txt || true" not in content


def test_ci_targets_the_main_default_branch():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "branches: [ main ]" in ci


def test_readme_documents_security_configuration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "AGENT_AUTH_REQUIRED" in readme
    assert "AGENT_API_KEYS" in readme
    assert "AGENT_HTTP_ALLOWED_HOSTS" in readme


def test_readme_documents_vector_memory_migration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Copy-Item .\\vector_memory.json .\\data\\vector_memory.json" in readme
    assert "旧版向量记忆" in readme


def test_compose_forwards_gemini_configuration():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "GEMINI_API_KEY: ${GEMINI_API_KEY:-}" in compose
    assert "GEMINI_MODEL: ${GEMINI_MODEL:-gemini-3.6-flash}" in compose
    assert "GEMINI_EMBEDDING_MODEL: ${GEMINI_EMBEDDING_MODEL:-gemini-embedding-2}" in compose
    assert "AGENT_LLM_BACKEND: ${AGENT_LLM_BACKEND:-mock}" in compose
    assert "AGENT_EMBEDDING_BACKEND: ${AGENT_EMBEDDING_BACKEND:-mock}" in compose


def test_compose_forwards_qwen_configuration():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}" in compose
    assert "QWEN_MODEL: ${QWEN_MODEL:-qwen-plus}" in compose
    assert (
        "DASHSCOPE_BASE_URL: ${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"
        in compose
    )
    assert "AGENT_LLM_BACKEND=qwen" in readme
    assert "DASHSCOPE_API_KEY" in readme
    assert "QWEN_MODEL" in readme
    assert "DASHSCOPE_BASE_URL" in readme


def test_compose_configures_persistent_workflow_store():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "AGENT_GUIDE.md").read_text(encoding="utf-8")

    assert "WORKFLOW_STORE_PATH: ${WORKFLOW_STORE_PATH:-/app/data/workflows.sqlite3}" in compose
    assert "WORKFLOW_STORE_PATH" in readme
    assert "重启" in readme
    assert "WORKFLOW_STORE_PATH" in guide


def test_compose_mounts_plugins_read_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "./plugins:/app/plugins:ro" in compose
    assert "AGENT_CAPABILITY_RUNTIME_ENABLED: ${AGENT_CAPABILITY_RUNTIME_ENABLED:-false}" in compose


def test_compose_forwards_and_documents_mcp_security_allowlists():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "AGENT_GUIDE.md").read_text(encoding="utf-8")

    assert "AGENT_MCP_ALLOWED_HOSTS: ${AGENT_MCP_ALLOWED_HOSTS:-}" in compose
    assert (
        "AGENT_MCP_STDIO_ALLOWED_COMMANDS: ${AGENT_MCP_STDIO_ALLOWED_COMMANDS:-}"
        in compose
    )
    assert "AGENT_MCP_ALLOWED_HOSTS" in readme
    assert "AGENT_MCP_STDIO_ALLOWED_COMMANDS" in readme
    assert "Python 3.11+" in guide


def test_compose_forwards_and_documents_mcp_lifecycle_timeouts():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    defaults = {
        "AGENT_MCP_STARTUP_TIMEOUT_SECONDS": "30",
        "AGENT_MCP_DISCOVERY_TIMEOUT_SECONDS": "30",
        "AGENT_MCP_SHUTDOWN_TIMEOUT_SECONDS": "10",
    }

    for variable, default in defaults.items():
        assert f"{variable}: ${{{variable}:-{default}}}" in compose
        assert variable in readme


def test_compose_and_docs_cover_structured_mcp_tool_calling():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert _compose_default("AGENT_STRUCTURED_TOOL_CALLING_ENABLED") == "false"
    assert "AGENT_STRUCTURED_TOOL_CALLING_ENABLED" in readme
    assert "`name`、`description`、`input_schema`、`side_effects`、`idempotent`" in readme
    assert "CapabilityRegistry.invoke()" in readme
    assert "远端 MCP 服务仍必须自行执行租户鉴权" in readme
    assert "`/api/handle`" in readme
    assert "SQLite" in readme
    assert "不支持结构化 MCP 工具调用" in readme
    activation_start = readme.index("如需启用结构化 MCP 工具调用")
    runtime_index = readme.index("AGENT_CAPABILITY_RUNTIME_ENABLED=true", activation_start)
    hosts_allowlist_index = readme.index("AGENT_MCP_ALLOWED_HOSTS", activation_start)
    stdio_allowlist_index = readme.index(
        "AGENT_MCP_STDIO_ALLOWED_COMMANDS", activation_start
    )
    structured_index = readme.index(
        "AGENT_STRUCTURED_TOOL_CALLING_ENABLED=true", activation_start
    )
    activation_end = readme.index("\n", activation_start)
    activation_line = readme[activation_start:activation_end]

    assert runtime_index < hosts_allowlist_index < structured_index
    assert runtime_index < stdio_allowlist_index < structured_index
    assert "默认值始终为 `false`" in activation_line
    assert (
        "请求/API Key\n"
        "    -> 输入清理与用户隔离\n"
        "    -> Planner 生成步骤\n"
        "    -> ToolCall\n"
        "    -> CapabilityRegistry 校验参数/timeout 并分发\n"
        "    -> 本地工具处理器或插件 MCP 客户端\n"
        "    -> 规范化 ToolResult\n"
        "    -> 结果大小检查与稳定错误状态\n"
        "    -> Executor 继续后续步骤或返回同步响应/持久化队列状态"
        in architecture
    )


def test_compose_forwards_global_tool_result_limit():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "AGENT_MAX_TOOL_RESULT_BYTES: ${AGENT_MAX_TOOL_RESULT_BYTES:-1048576}" in compose


def test_docker_build_context_excludes_local_runtime_data():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for entry in (".git", ".worktrees", "data", "tests", "docs", "*.log", "*.sqlite3", "vector_memory.json"):
        assert entry in dockerignore
    assert "*.json" not in dockerignore


def test_dockerfile_copies_only_runtime_inputs():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY . /app" not in dockerfile
    assert "COPY requirements.txt /app/requirements.txt" in dockerfile
    assert "COPY src /app/src" in dockerfile
    assert "COPY plugins /app/plugins" in dockerfile


def test_development_mode_accepts_existing_defaults():
    result = _import_config_with_environment(AGENT_DEPLOYMENT_MODE="development")

    assert result.returncode == 0, result.stderr


def test_production_mode_rejects_disabled_authentication():
    result = _import_config_with_environment(
        AGENT_DEPLOYMENT_MODE="production",
        AGENT_AUTH_REQUIRED="false",
        AGENT_API_KEYS="worker:strong-key",
        AGENT_METRICS_API_KEY="strong-metrics-key",
        AGENT_HTTP_ALLOWED_HOSTS="api.example.com",
    )

    assert result.returncode != 0
    assert "AGENT_AUTH_REQUIRED" in result.stderr


def test_production_mode_rejects_missing_api_keys():
    result = _import_config_with_environment(
        AGENT_DEPLOYMENT_MODE="production",
        AGENT_AUTH_REQUIRED="true",
        AGENT_METRICS_API_KEY="strong-metrics-key",
        AGENT_HTTP_ALLOWED_HOSTS="api.example.com",
    )

    assert result.returncode != 0
    assert "AGENT_API_KEYS" in result.stderr


def test_production_mode_rejects_default_metrics_token():
    result = _import_config_with_environment(
        AGENT_DEPLOYMENT_MODE="production",
        AGENT_AUTH_REQUIRED="true",
        AGENT_API_KEYS="worker:strong-key",
        AGENT_METRICS_API_KEY="local-dev-metrics",
        AGENT_HTTP_ALLOWED_HOSTS="api.example.com",
    )

    assert result.returncode != 0
    assert "AGENT_METRICS_API_KEY" in result.stderr


def test_production_mode_rejects_missing_http_allowlist():
    result = _import_config_with_environment(
        AGENT_DEPLOYMENT_MODE="production",
        AGENT_AUTH_REQUIRED="true",
        AGENT_API_KEYS="worker:strong-key",
        AGENT_METRICS_API_KEY="strong-metrics-key",
    )

    assert result.returncode != 0
    assert "AGENT_HTTP_ALLOWED_HOSTS" in result.stderr


def test_production_mode_accepts_complete_configuration():
    result = _import_config_with_environment(
        AGENT_DEPLOYMENT_MODE="production",
        AGENT_AUTH_REQUIRED="true",
        AGENT_API_KEYS="worker:strong-key",
        AGENT_METRICS_API_KEY="strong-metrics-key",
        AGENT_HTTP_ALLOWED_HOSTS="api.example.com",
    )

    assert result.returncode == 0, result.stderr


def test_production_compose_requires_security_variables():
    compose = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert "AGENT_DEPLOYMENT_MODE: production" in compose
    assert "AGENT_AUTH_REQUIRED: \"true\"" in compose
    assert "${AGENT_API_KEYS:?" in compose
    assert "${AGENT_METRICS_API_KEY:?" in compose
    assert "${AGENT_HTTP_ALLOWED_HOSTS:?" in compose


def test_prometheus_ui_binds_only_to_localhost():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    production = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")

    assert '127.0.0.1:9090:9090' in compose
    assert "ports: []" not in production


def test_ci_and_release_install_development_dependencies_and_check_them():
    workflows = [
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
    ]

    for workflow in workflows:
        assert "pip install -r requirements-dev.txt" in workflow
        assert "python -m pip check" in workflow


def test_ci_validates_compose_and_builds_the_image():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "docker compose config --quiet" in ci
    assert "docker build --tag minimal-agent:ci ." in ci
