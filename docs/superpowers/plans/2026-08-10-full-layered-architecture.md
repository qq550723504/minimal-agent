# Full Layered Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `src.agent` into API, application, domain, infrastructure, security, and tools packages without changing runtime behavior or retaining old import paths.

**Architecture:** Move cohesive modules into layer-specific packages and update every production, test, and documentation import to canonical paths. Split the API module into app construction, schemas, and routes; preserve endpoint behavior and lifespan ordering. Keep only configuration, observability, namespaces, tool registry, and version metadata at package root.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, SQLite, MCP SDK.

## Global Constraints

- Preserve HTTP paths, response schemas, lifecycle behavior, environment-variable names, persistence schema, plugin manifests, and runtime semantics.
- Delete old root modules and leave no compatibility re-exports.
- Dependency direction is `api -> application -> domain`; infrastructure does not import API.
- Run focused pytest tests after each task and `pytest -q` before completion.

---

## File Structure

| Target | Responsibility | Source |
| --- | --- | --- |
| `domain/capabilities/` | Capability models, registry, errors | `capabilities/` |
| `domain/planning/models.py` | Plan item contracts and normalization | `plan_models.py` |
| `security/` | Auth, input/audit, URL security | `auth.py`, `security.py`, `http_security.py` |
| `infrastructure/llm/` | LLM adapters and factories | `llm*.py` |
| `infrastructure/memory/` | Embeddings, vectors, memory | `embeddings*.py`, `memory*.py`, `vector_*.py` |
| `infrastructure/workflows/` | Queue and SQLite store | `task_queue.py`, `workflow_store.py` |
| `infrastructure/mcp/` | MCP adapter, manager, transport, security | `mcp/` |
| `infrastructure/plugins/`, `skills/` | Plugin and skill runtime | `plugins/`, `skills/` |
| `application/planning/`, `execution/` | Plan and execution orchestration | `planner.py`, `executor.py` |
| `application/requests.py` | Input request orchestration | `main.py` |
| `api/` | FastAPI app, schemas, routes | `server.py` |

### Task 1: Establish domain and security packages

**Files:**
- Create: `src/agent/domain/__init__.py`, `src/agent/domain/planning/__init__.py`, `src/agent/security/__init__.py`
- Move: `capabilities/` â†?`domain/capabilities/`; `plan_models.py` â†?`domain/planning/models.py`; `auth.py` â†?`security/auth.py`; `security.py` â†?`security/input.py`; `http_security.py` â†?`security/http.py`
- Modify: all affected source and test imports
- Test: `tests/test_capability_models.py`, `tests/test_capability_registry.py`, `tests/test_security.py`, `tests/test_http_tool.py`

**Interfaces:**
- Produces `src.agent.domain.capabilities.*`, `src.agent.domain.planning.models`, `src.agent.security.auth`, `src.agent.security.input`, and `src.agent.security.http`.
- Existing public types/functions retain their signatures.

- [ ] **Step 1: Write the failing canonical-import test**

```python
from src.agent.domain.capabilities.models import ToolCall, ToolSpec
from src.agent.security.input import sanitize_input

def test_canonical_domain_and_security_imports():
    assert ToolCall is not None
    assert ToolSpec is not None
    assert sanitize_input("hello") == "hello"
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_domain_and_security_imports -v`

Expected: FAIL because the canonical packages do not exist.

- [ ] **Step 3: Implement the move**

Use `Move-Item` for each source path, create package initializers, and replace every import of `capabilities`, `plan_models`, `auth`, `security`, and `http_security` with the paths above. Do not leave modules at their former paths.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_capability_models.py tests/test_capability_registry.py tests/test_security.py tests/test_http_tool.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/domain src/agent/security tests
git commit -m "refactor: organize domain and security modules"
```

### Task 2: Move LLM and memory infrastructure

**Files:**
- Create: `src/agent/infrastructure/__init__.py`, `infrastructure/llm/__init__.py`, `infrastructure/memory/__init__.py`
- Move: `llm.py`, `llm_factory.py`, `llm_openai.py`, `llm_gemini.py`, `llm_compatible.py` â†?`infrastructure/llm/`
- Move: `embeddings.py`, `embeddings_factory.py`, `embeddings_openai.py`, `embeddings_gemini.py`, `memory.py`, `memory_manager.py`, `vector_store.py`, `vector_memory.py` â†?`infrastructure/memory/`
- Modify: source and test imports
- Test: `tests/test_llm*.py`, `tests/test_embeddings_factory.py`, `tests/test_vector_*.py`, `tests/test_memory*.py`

**Interfaces:**
- Consumes domain planning models and `src.agent.config`.
- Produces canonical LLM adapters/factory and memory/vector modules, retaining all public names.

- [ ] **Step 1: Write the failing import test**

```python
from src.agent.infrastructure.llm.llm import MockLLM
from src.agent.infrastructure.memory.vector_memory import VectorMemory

def test_canonical_model_and_memory_imports():
    assert MockLLM is not None
    assert VectorMemory is not None
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_model_and_memory_imports -v`

Expected: FAIL because infrastructure packages do not exist.

- [ ] **Step 3: Implement the move**

Move each listed module, then replace LLM imports of `src.agent.plan_models` with `src.agent.domain.planning.models`. Keep configuration imports rooted at `src.agent.config`; update all callers and tests to canonical infrastructure imports.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_llm.py tests/test_llm_openai.py tests/test_llm_gemini.py tests/test_embeddings_factory.py tests/test_vector_store.py tests/test_vector_memory.py tests/test_memory_manager.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/infrastructure tests
git commit -m "refactor: organize llm and memory infrastructure"
```

### Task 3: Move runtime infrastructure

**Files:**
- Create: `infrastructure/workflows/__init__.py`
- Move: `task_queue.py`, `workflow_store.py` â†?`infrastructure/workflows/`; `mcp/`, `plugins/`, `skills/` â†?matching `infrastructure/` packages
- Modify: source and test imports
- Test: `tests/test_task_queue.py`, `tests/test_persistent_task_queue.py`, `tests/test_workflow_store.py`, `tests/test_plugin_loader.py`, `tests/test_skill_runtime.py`, `tests/test_mcp_manager.py`, `tests/test_mcp_transports.py`

**Interfaces:**
- Produces canonical workflow queue/store, plugin catalog/loader, skill catalog/resolver/reference tool, and MCP manager/adapter/transport imports.
- MCP uses domain capability contracts and security modules; no infrastructure module imports API.

- [ ] **Step 1: Write the failing import test**

```python
from src.agent.infrastructure.workflows.workflow_store import WorkflowStore
from src.agent.infrastructure.plugins.loader import PluginLoader
from src.agent.infrastructure.mcp.manager import MCPClientManager

def test_canonical_runtime_infrastructure_imports():
    assert all((WorkflowStore, PluginLoader, MCPClientManager))
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_runtime_infrastructure_imports -v`

Expected: FAIL because target packages do not exist.

- [ ] **Step 3: Implement the move**

Move the modules and directories to their targets. Update MCP imports to `domain.capabilities` and security imports to `security.*`; update all application callers and tests.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_task_queue.py tests/test_persistent_task_queue.py tests/test_workflow_store.py tests/test_plugin_loader.py tests/test_skill_runtime.py tests/test_mcp_manager.py tests/test_mcp_transports.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/infrastructure tests
git commit -m "refactor: organize runtime infrastructure"
```

### Task 4: Create application services

**Files:**
- Create: `src/agent/application/__init__.py`, `application/planning/__init__.py`, `application/execution/__init__.py`
- Move: `planner.py` â†?`application/planning/service.py`; `executor.py` â†?`application/execution/service.py`
- Modify: source and test imports
- Test: `tests/test_planner.py`, `tests/test_executor.py`, `tests/test_persistent_executor.py`, `tests/test_structured_tool_runtime.py`

**Interfaces:**
- Produces `plan_task`, `build_plan_summary`, `execute_plan_items`, `enqueue_task_execution`, `WorkflowRunner`, and `DurableWorkflowRunner` at application canonical paths.

- [ ] **Step 1: Write the failing import test**

```python
from src.agent.application.planning.service import plan_task
from src.agent.application.execution.service import execute_plan_items

def test_canonical_application_imports():
    assert callable(plan_task)
    assert callable(execute_plan_items)
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_application_imports -v`

Expected: FAIL because application packages do not exist.

- [ ] **Step 3: Implement the move**

Move both modules. Replace imports with canonical domain and infrastructure imports. Keep all function signatures and legacy workflow behavior unchanged.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_planner.py tests/test_executor.py tests/test_persistent_executor.py tests/test_structured_tool_runtime.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/application tests
git commit -m "refactor: organize planning and execution services"
```

### Task 5: Move request orchestration and update built-in tools

**Files:**
- Move: `main.py` â†?`application/requests.py`
- Modify: `tool_registry.py`, `tools/__init__.py`, `tools/http_tool.py`, `namespaces.py`, all callers
- Test: `tests/test_agent.py`, `tests/test_tool_registry.py`, `tests/test_server_tools.py`

**Interfaces:**
- Produces `handle_input_async`, `handle_input`, `enqueue_input`, and `main_loop` from `src.agent.application.requests`.
- Built-in tools consume domain capability contracts and `src.agent.security.http`.

- [ ] **Step 1: Write the failing import test**

```python
from src.agent.application.requests import handle_input_async

def test_canonical_request_orchestration_import():
    assert callable(handle_input_async)
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_request_orchestration_import -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the move**

Move `main.py`, change all callers and tests from `src.agent.main`, and update tool registry/HTTP tool imports to domain and security canonical modules.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_agent.py tests/test_tool_registry.py tests/test_server_tools.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/application src/agent/tool_registry.py src/agent/tools tests
git commit -m "refactor: move request orchestration into application layer"
```

### Task 6: Split the FastAPI layer

**Files:**
- Create: `src/agent/api/__init__.py`, `api/schemas.py`, `api/routes/__init__.py`, `api/routes/handle.py`, `api/routes/catalog.py`, `api/routes/docs.py`, `api/app.py`
- Delete: `src/agent/server.py`
- Modify: `Dockerfile`, `README.md`, API test imports
- Test: `tests/test_server.py`, `tests/test_persistent_api.py`, `tests/test_plugin_api.py`, `tests/test_server_tools.py`, `tests/test_structured_tool_runtime.py`

**Interfaces:**
- Produces `src.agent.api.app:app` as the only uvicorn target, preserving existing routes and application lifespan behavior.

- [ ] **Step 1: Write the failing app import and route test**

```python
from fastapi.testclient import TestClient
from src.agent.api.app import app

def test_canonical_api_app_exposes_root_route():
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_import_layout.py::test_canonical_api_app_exposes_root_route -v`

Expected: FAIL because `src.agent.api.app` does not exist.

- [ ] **Step 3: Implement the API split**

Put Pydantic request/response classes in `api/schemas.py`; move handle/queue/task routes to `routes/handle.py`, catalog routes to `routes/catalog.py`, and docs/OpenAPI routes to `routes/docs.py`. Put the application instance, existing exception handler, metrics setup, and unchanged startup/shutdown ordering in `api/app.py`. Update Docker and README from `src.agent.server:app` to `src.agent.api.app:app`.

- [ ] **Step 4: Verify focused behavior**

Run: `pytest tests/test_import_layout.py tests/test_server.py tests/test_persistent_api.py tests/test_plugin_api.py tests/test_server_tools.py tests/test_structured_tool_runtime.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/api Dockerfile README.md tests
git commit -m "refactor: split api application and routes"
```

### Task 7: Remove obsolete paths and verify the refactor

**Files:**
- Delete: all former modules/directories moved in Tasks 1-6
- Modify: `README.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_GUIDE.md`, `docs/MCP_INTEGRATION.md`, `docker-compose.yml`, `docker-compose.production.yml` where imports or startup targets are documented
- Test: `tests/test_import_layout.py`, complete suite

**Interfaces:**
- Produces a repository with only canonical imports and no old root-level implementation modules.

- [ ] **Step 1: Write negative legacy-path assertions**

```python
from pathlib import Path

def test_obsolete_root_modules_are_removed():
    root = Path("src/agent")
    assert not (root / "server.py").exists()
    assert not (root / "main.py").exists()
    assert not (root / "executor.py").exists()
    assert not (root / "planner.py").exists()
```

- [ ] **Step 2: Verify the cleanup test**

Run: `pytest tests/test_import_layout.py::test_obsolete_root_modules_are_removed -v`

Expected: PASS only after legacy files are removed.

- [ ] **Step 3: Remove paths and replace every remaining project reference**

Run: `rg -n "from src\\.agent\\.(server|main|planner|executor|llm|memory|mcp|plugins|skills|capabilities|plan_models)|import src\\.agent\\.(server|main|planner|executor|llm|memory|mcp|plugins|skills|capabilities|plan_models)" src tests docs README.md Dockerfile docker-compose.yml docker-compose.production.yml`

Expected: no matches after all canonical replacements.

- [ ] **Step 4: Run final verification**

Run: `pytest -q`

Expected: all tests PASS.

Run: `python -c "from src.agent.api.app import app; assert app.openapi()['openapi']; print(app.title)"`

Expected: exits 0 and prints the existing application title.

- [ ] **Step 5: Commit**

```bash
git add src tests README.md docs Dockerfile docker-compose.yml docker-compose.production.yml
git commit -m "refactor: complete layered architecture migration"
```


