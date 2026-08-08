# Plugin and Skill Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load administrator-installed declarative plugins and deterministically activate safe, read-only Skills without executing plugin Python code.

**Architecture:** A strict Pydantic manifest owns Plugin, Skill, and future MCP declarations. `PluginLoader` resolves every path inside one configured root, `SkillCatalog` selects namespaced Skills, and a built-in capability reads only UTF-8 reference files belonging to active Skills.

**Tech Stack:** Python 3.11, Pydantic 2.13.4, PyYAML 6.0.3, pathlib, FastAPI, pytest.

## Global Constraints

- This plan requires the completed Capability Runtime Foundation plan.
- Plugin installation is local-directory-only and startup-only; no upload, marketplace, download, or hot reload.
- Plugin manifests are data, not executable entry points.
- Skill IDs are `<plugin-id>.<skill-id>` and tool names remain namespaced.
- Unknown YAML fields, duplicate IDs, missing declared paths, path escape, symlink escape, and non-UTF-8 Skill files are rejected.
- Explicit `skill_ids` suppress trigger-based additions; otherwise normalized full-phrase trigger containment selects at most `AGENT_MAX_ACTIVE_SKILLS` Skills.
- MCP declarations are validated and retained but are not connected in this plan.

---

## File Map

- Create `src/agent/plugins/__init__.py`, `models.py`, `loader.py`, `catalog.py`.
- Create `src/agent/skills/__init__.py`, `models.py`, `loader.py`, `resolver.py`, `reference_tool.py`.
- Modify `src/agent/config.py:4-17` for plugin and Skill limits.
- Modify `src/agent/server.py:30-132` for catalog discovery endpoints only.
- Modify `requirements.txt` to pin PyYAML.
- Modify `docker-compose.yml` to mount `./plugins:/app/plugins:ro` only when enabled.
- Create `plugins/.gitkeep`.
- Modify `README.md` and `docs/AGENT_GUIDE.md`.
- Create `tests/test_plugin_models.py`, `test_plugin_loader.py`, `test_skill_runtime.py`, `test_plugin_api.py`.

### Task 1: Define strict plugin manifest models

**Files:**
- Create: `src/agent/plugins/__init__.py`
- Create: `src/agent/plugins/models.py`
- Modify: `requirements.txt`
- Test: `tests/test_plugin_models.py`

**Interfaces:**
- Produces: `PluginManifest`, `SkillManifest`, `AllowedToolManifest`, `StdioMCPServerManifest`, `HTTPMCPServerManifest`, `MCPServerManifest`.

- [ ] **Step 1: Write failing manifest tests**

```python
import pytest
from pydantic import ValidationError

from src.agent.plugins.models import PluginManifest


def test_manifest_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "surprise": True,
        })


def test_allowed_tool_requires_retry_semantics():
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "mcp_servers": [{
                "id": "remote",
                "transport": "streamable_http",
                "url_env": "DEMO_URL",
                "allowed_tools": [{"name": "search"}],
            }],
        })
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_plugin_models.py -q`

Expected: FAIL with missing `src.agent.plugins.models`.

- [ ] **Step 3: Pin YAML and implement discriminated models**

Add `PyYAML==6.0.3`. Use `ConfigDict(extra="forbid")` on every manifest model and these transport shapes:

```python
class AllowedToolManifest(BaseModel):
    name: str
    side_effects: bool
    idempotent: bool
    timeout_seconds: float = Field(default=30.0, gt=0)
    result_size_limit: int = Field(default=1_048_576, gt=0)


class StdioMCPServerManifest(BaseModel):
    id: str
    transport: Literal["stdio"]
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[AllowedToolManifest]


class HTTPMCPServerManifest(BaseModel):
    id: str
    transport: Literal["streamable_http"]
    url_env: str
    headers_env: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[AllowedToolManifest]
```

`PluginManifest.required` defaults to `False`; `api_version` is `Literal["minimal-agent/v1"]`; model validators reject duplicate Skill IDs, MCP IDs, triggers, and allowed tool names.

- [ ] **Step 4: Run model tests**

Run: `python -m pytest tests/test_plugin_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit manifest contracts**

```powershell
git add requirements.txt src/agent/plugins tests/test_plugin_models.py
git commit -m "feat: define declarative plugin manifests"
```

### Task 2: Load plugins with path containment and stable status

**Files:**
- Create: `src/agent/plugins/loader.py`
- Create: `src/agent/plugins/catalog.py`
- Modify: `src/agent/plugins/__init__.py`
- Modify: `src/agent/config.py:4-17`
- Test: `tests/test_plugin_loader.py`

**Interfaces:**
- Consumes: `PluginManifest`.
- Produces: `LoadedPlugin`, `PluginStatus`, `PluginCatalog`, `PluginLoader.load_all() -> PluginCatalog`; `PluginCatalog.statuses` is keyed by installation directory name so duplicate manifest IDs can both be reported.

- [ ] **Step 1: Write failing loader tests**

```python
def test_loader_rejects_skill_path_outside_plugin(tmp_path):
    plugin = tmp_path / "plugins" / "demo"
    plugin.mkdir(parents=True)
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (plugin / "plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: demo
version: 1.0.0
skills:
  - id: bad
    path: ../../outside.md
""",
        encoding="utf-8",
    )

    catalog = PluginLoader(tmp_path / "plugins").load_all()
    assert catalog.statuses["demo"].state == "disabled"
    assert catalog.statuses["demo"].error_code == "plugin_path_escape"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_plugin_loader.py -q`

Expected: FAIL because `PluginLoader` is missing.

- [ ] **Step 3: Implement safe, deterministic loading**

```python
class PluginLoader:
    def __init__(self, plugin_root: Path):
        self.plugin_root = plugin_root

    def load_all(self) -> PluginCatalog:
        manifests = sorted(self.plugin_root.glob("*/plugin.yaml"))
        return self._load_manifests(manifests)


def resolve_inside(root: Path, relative: str) -> Path:
    unresolved = root / relative
    existing_parts = [unresolved, *unresolved.parents]
    if any(part.is_symlink() for part in existing_parts if part.exists()):
        raise PluginLoadError("plugin_path_escape")
    candidate = unresolved.resolve(strict=True)
    candidate.relative_to(root.resolve(strict=True))
    return candidate
```

Use `yaml.safe_load`, scan `*/plugin.yaml` sorted by directory name, reject duplicate Plugin IDs across directories, and store stable `error_code` values without secret-bearing exception reprs. A malformed `required: true` plugin raises `RequiredPluginError`; an optional plugin receives disabled status.

- [ ] **Step 4: Cover required/optional, duplicate, YAML, junction, and UTF-8 cases**

```python
def test_required_plugin_error_stops_loading(tmp_path):
    write_plugin(tmp_path, "required", required=True, skill_path="missing/SKILL.md")
    with pytest.raises(RequiredPluginError):
        PluginLoader(tmp_path).load_all()


def test_duplicate_plugin_id_disables_second_plugin(tmp_path):
    write_plugin(tmp_path, "one", plugin_id="same")
    write_plugin(tmp_path, "two", plugin_id="same")
    catalog = PluginLoader(tmp_path).load_all()
    assert catalog.statuses["two"].error_code == "duplicate_plugin_id"
```

Add named tests for malformed YAML, a directory junction/symlink escape, and invalid UTF-8 `SKILL.md`; assert stable error codes rather than platform exception text.

Run: `python -m pytest tests/test_plugin_models.py tests/test_plugin_loader.py -q`

Expected: PASS.

- [ ] **Step 5: Commit plugin loading**

```powershell
git add src/agent/config.py src/agent/plugins tests/test_plugin_loader.py
git commit -m "feat: load administrator-installed plugins safely"
```

### Task 3: Build deterministic Skill selection and reference reading

**Files:**
- Create: `src/agent/skills/__init__.py`
- Create: `src/agent/skills/models.py`
- Create: `src/agent/skills/loader.py`
- Create: `src/agent/skills/resolver.py`
- Create: `src/agent/skills/reference_tool.py`
- Test: `tests/test_skill_runtime.py`

**Interfaces:**
- Consumes: `PluginCatalog`, `CapabilityRegistry`, `ToolInvocationContext.active_skill_ids`.
- Produces: `SkillDefinition`, `SkillCatalog`, `SkillResolver.resolve(prompt, explicit_ids)`, and `register_skill_reference_tool()`.

- [ ] **Step 1: Write failing resolver and reference tests**

```python
def test_explicit_skills_suppress_trigger_additions(skill_catalog):
    resolver = SkillResolver(skill_catalog, max_active=3)
    selected = resolver.resolve("please review pull request", ["demo.manual"])
    assert [skill.id for skill in selected] == ["demo.manual"]


@pytest.mark.anyio
async def test_reference_tool_rejects_inactive_skill(reference_registry):
    result = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "guide.md"},
        ),
        ToolInvocationContext(active_skill_ids=()),
    )
    assert result.error_code == "inactive_skill"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_skill_runtime.py -q`

Expected: FAIL with missing Skill runtime modules.

- [ ] **Step 3: Implement exact resolution rules**

```python
def normalize_trigger(value: str) -> str:
    return " ".join(value.casefold().strip().split())


class SkillResolver:
    def resolve(self, prompt: str, explicit_ids: list[str] | None) -> list[SkillDefinition]:
        if explicit_ids:
            return self._resolve_explicit(explicit_ids)
        normalized = normalize_trigger(prompt)
        matches = [
            skill for skill in self.catalog.sorted()
            if any(normalize_trigger(trigger) in normalized for trigger in skill.triggers)
        ]
        return matches[: self.max_active]
```

Reference arguments are exactly `skill_id` and `path`. Read only regular UTF-8 files under the selected Skill's `references/` directory, reject absolute paths and links, and enforce `AGENT_MAX_SKILL_REFERENCE_BYTES` before decoding.

- [ ] **Step 4: Run Skill and capability tests**

Run: `python -m pytest tests/test_skill_runtime.py tests/test_capability_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Skill runtime**

```powershell
git add src/agent/skills tests/test_skill_runtime.py
git commit -m "feat: add deterministic declarative skills"
```

### Task 4: Expose read-only catalogs and deployment configuration

**Files:**
- Modify: `src/agent/server.py:30-132`
- Modify: `src/agent/config.py`
- Modify: `docker-compose.yml`
- Create: `plugins/.gitkeep`
- Modify: `README.md`
- Modify: `docs/AGENT_GUIDE.md`
- Test: `tests/test_plugin_api.py`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Consumes: `PluginCatalog`, `SkillCatalog`.
- Produces: authenticated `GET /api/plugins` and `GET /api/skills`.

- [ ] **Step 1: Write failing authenticated API tests**

```python
def test_plugin_and_skill_catalogs_require_auth(monkeypatch):
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "alice:secret")
    client = TestClient(server.app)
    assert client.get("/api/plugins").status_code == 401
    assert client.get("/api/skills").status_code == 401
    assert client.get("/api/plugins", headers={"X-API-Key": "secret"}).status_code == 200
```

- [ ] **Step 2: Run and confirm 404 failures**

Run: `python -m pytest tests/test_plugin_api.py -q`

Expected: FAIL because catalog routes do not exist.

- [ ] **Step 3: Add catalog state and response models**

Expose only IDs, versions, enabled/disabled state, stable error codes, triggers, and declared capability names. Do not return environment variable values, headers, commands with expanded secrets, Skill instructions, or reference contents.

When `CAPABILITY_RUNTIME_ENABLED` is true, the existing startup hook loads `PluginCatalog`, builds `SkillCatalog`, registers `internal.skill_read_reference`, and stores both catalogs on `app.state`; when false, it stores empty catalogs and does not touch the plugin directory. Required plugin errors propagate out of startup. The MCP plan will later move this exact work into the unified lifespan.

Add configuration defaults:

```python
CAPABILITY_RUNTIME_ENABLED = _bool_env("AGENT_CAPABILITY_RUNTIME_ENABLED", "false")
PLUGIN_DIR = os.getenv("AGENT_PLUGIN_DIR", "plugins").strip()
MAX_ACTIVE_SKILLS = int(os.getenv("AGENT_MAX_ACTIVE_SKILLS", "3"))
MAX_SKILL_REFERENCE_BYTES = int(os.getenv("AGENT_MAX_SKILL_REFERENCE_BYTES", "262144"))
```

- [ ] **Step 4: Document and test deployment wiring**

Add Compose variables and the read-only `./plugins:/app/plugins:ro` mount. Update deployment tests to assert the runtime defaults to disabled and the plugin mount is read-only.

```python
def test_compose_mounts_plugins_read_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./plugins:/app/plugins:ro" in compose
    assert "AGENT_CAPABILITY_RUNTIME_ENABLED=${AGENT_CAPABILITY_RUNTIME_ENABLED:-false}" in compose
```

Run: `python -m pytest tests/test_plugin_api.py tests/test_deployment_config.py -q`

Expected: PASS.

- [ ] **Step 5: Run regression and commit**

Run: `python -m pytest -q`

Expected: all tests PASS.

```powershell
git add src/agent/server.py src/agent/config.py docker-compose.yml plugins README.md docs/AGENT_GUIDE.md tests/test_plugin_api.py tests/test_deployment_config.py
git commit -m "feat: expose plugin and skill catalogs"
```

## Plan Completion Gate

Run:

```powershell
python -m pip check
python -m pytest -q
git diff --check
```

Expected: all commands succeed. Manually inspect `/api/plugins` output from a fixture plugin and confirm no environment values or Skill contents are present.
