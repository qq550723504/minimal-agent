from pathlib import Path


ROOT = Path(__file__).parents[1]


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
