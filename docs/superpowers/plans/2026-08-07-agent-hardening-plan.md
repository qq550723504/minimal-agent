# Agent Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Agent prototype execute asynchronous plans as ordered workflows, enforce user ownership and HTTP egress policy, isolate vector memory, and run reproducibly in CI and Compose.

**Architecture:** Keep FastAPI, the standard-library in-process queue, and adapter interfaces. Add small authentication and HTTP policy modules, pass the authenticated owner through planner and queue APIs, and make one queue record represent one workflow. Use atomic vector-memory writes and explicit validation rather than adding a database.

**Tech Stack:** Python 3.11 runtime, FastAPI/Pydantic, `requests`, `pytest`, `prometheus_client`, standard-library `ipaddress`, `socket`, `tempfile`, `os.replace`, and Docker Compose.

## Global Constraints

- Preserve the existing synchronous `handle_input(prompt)` behavior for callers that omit a user ID.
- Use `default` as the development fallback owner only when authentication is not required.
- Do not make real OpenAI requests in tests.
- HTTP tools must default to deny when `AGENT_HTTP_ALLOWED_HOSTS` is empty.
- Do not introduce Redis, Celery, a database, or a new runtime service.
- Stage only files belonging to this plan.

---

### Task 1: Add ordered workflow execution

**Files:**
- Modify: `src/agent/executor.py`
- Modify: `src/agent/main.py`
- Modify: `src/agent/task_queue.py`
- Modify: `src/agent/config.py`
- Test: `tests/test_executor.py`
- Test: `tests/test_task_queue.py`

**Interfaces:**
- `execute_workflow(steps: List[Any]) -> List[str]` executes steps in input order and raises `WorkflowExecutionError` with `step_index` when a step fails.
- `enqueue_task_execution(steps: List[Any], owner_id: str = "default", max_retries: int = 0, retry_delay: float = 0.0) -> dict` returns `{"status": "queued", "task_id": str, "task_ids": [str]}` for compatibility.
- `TaskRecord.owner_id: str` and `TaskRecord.failed_step: Optional[int]` are exposed in task responses.

- [ ] **Step 1: Write failing workflow tests.**

Add a test that calls `execute_workflow` with steps that append markers and asserts the returned list and marker order. Add a test that enqueues a two-step workflow with two workers and asserts exactly one task ID, a completed record, and ordered results. Add a failure test asserting `failed_step == 1` after the second step raises.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing workflow behavior.**

Run:

```powershell
python -m pytest -q tests/test_executor.py tests/test_task_queue.py
```

Expected: the new workflow tests fail because `execute_workflow` and the one-task enqueue contract do not exist.

- [ ] **Step 3: Implement the minimal workflow path.**

Add `WorkflowExecutionError`, `execute_workflow`, and make `enqueue_task_execution` enqueue one callable that executes the complete list. Change structured tools to use the same tool execution path as text tools and let tool exceptions propagate so workflow failure is observable. Add `owner_id` and `failed_step` to `TaskRecord`; copy `step_index` from workflow exceptions in `_process_task`. Read `QUEUE_WORKER_COUNT` when constructing the global queue.

- [ ] **Step 4: Run focused tests and the existing executor/queue tests.**

Run the command above and expect all focused tests to pass. Confirm the existing retry test still records two attempts and a completed result.

- [ ] **Step 5: Commit the workflow slice.**

```powershell
git add src/agent/config.py src/agent/executor.py src/agent/main.py src/agent/task_queue.py tests/test_executor.py tests/test_task_queue.py
git commit -m "fix: execute queued plans as ordered workflows"
```

### Task 2: Add API-key authentication and task ownership

**Files:**
- Create: `src/agent/auth.py`
- Modify: `src/agent/server.py`
- Modify: `src/agent/main.py`
- Modify: `src/agent/planner.py`
- Modify: `src/agent/task_queue.py`
- Test: `tests/test_server.py`
- Test: `tests/test_server_tools.py`
- Test: `tests/test_task_queue.py`

**Interfaces:**
- `get_current_user(api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str` returns the mapped owner or raises HTTP 401 when `AGENT_AUTH_REQUIRED=true` and the key is absent/invalid.
- `AGENT_API_KEYS` uses comma-separated `user_id:key` entries.
- `handle_input(prompt: str, user_id: str = "default") -> str` and `enqueue_input(prompt: str, user_id: str = "default") -> dict` pass the owner into planning and queueing.
- Task lookups accept `owner_id` and return no records belonging to other owners.

- [ ] **Step 1: Write failing authentication and ownership tests.**

Use `monkeypatch` to set `AGENT_AUTH_REQUIRED=true` and `AGENT_API_KEYS=alice:secret,bob:other`. Assert `/api/tools` returns 401 without a key, succeeds for Alice with `X-API-Key: secret`, and rejects an invalid key. Enqueue a task as Alice and assert Bob receives 404 when querying its ID. Preserve a test for the development default when auth is disabled.

- [ ] **Step 2: Run the focused server tests and verify the new tests fail.**

Run:

```powershell
python -m pytest -q tests/test_server.py tests/test_server_tools.py tests/test_task_queue.py
```

Expected: the new requests are currently accepted without authentication and task records have no owner filter.

- [ ] **Step 3: Implement authentication and ownership propagation.**

Create `auth.py` with environment parsing and constant-time key comparison. Add FastAPI dependencies to `/api/handle`, `/api/handle/queue`, `/api/tasks`, `/api/tasks/{task_id}`, and `/api/tools`; keep `/` public. Pass the dependency result into `handle_input`, `enqueue_input`, `plan_task`, and queue records. Return 404 for missing or foreign task records. Add an exception handler mapping input `ValueError` to HTTP 400.

- [ ] **Step 4: Run focused tests and verify all pass.**

Run the command above. Also run `python -m pytest -q tests/test_planner.py tests/test_agent.py` to verify default user compatibility.

- [ ] **Step 5: Commit the authentication slice.**

```powershell
git add src/agent/auth.py src/agent/server.py src/agent/main.py src/agent/planner.py src/agent/task_queue.py tests/test_server.py tests/test_server_tools.py tests/test_task_queue.py
git commit -m "feat: authenticate API requests and isolate task ownership"
```

### Task 3: Enforce HTTP egress policy

**Files:**
- Create: `src/agent/http_security.py`
- Modify: `src/agent/tools/http_tool.py`
- Modify: `src/agent/tools/__init__.py`
- Test: `tests/test_http_tool.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- `validate_http_url(url: str, allowed_hosts: Optional[set[str]] = None) -> ParsedURL` rejects unsupported schemes, missing hosts, unapproved hosts, and unsafe resolved addresses.
- `call_http_get` and `call_http_post` use `AGENT_HTTP_ALLOWED_HOSTS`, `AGENT_HTTP_TIMEOUT_SECONDS`, `AGENT_HTTP_MAX_RESPONSE_BYTES`, and `AGENT_HTTP_ALLOW_PRIVATE=false`.

- [ ] **Step 1: Write failing policy tests.**

Add tests that reject an empty allowlist, `file://` URLs, `http://127.0.0.1`, and a hostname resolving to `169.254.169.254`; assert the patched requests client is not called. Add a permitted-host test using a patched DNS resolver returning `93.184.216.34`. Add tests for a 302 response and a response body exceeding the configured limit.

- [ ] **Step 2: Run HTTP tests and verify the new policy tests fail.**

Run:

```powershell
python -m pytest -q tests/test_http_tool.py tests/test_executor.py
```

Expected: current code calls the request client for all those destinations and follows the normal requests behavior.

- [ ] **Step 3: Implement URL validation and bounded JSON reads.**

Parse and normalize URLs with `urllib.parse`, resolve hostnames with `socket.getaddrinfo`, reject loopback/private/link-local/reserved/unspecified addresses unless the explicit development override is enabled, and require an exact configured hostname match. Use `allow_redirects=False`, bounded connect/read timeouts, `stream=True`, and `iter_content` to enforce the maximum response size before `json.loads`.

- [ ] **Step 4: Run focused tests and verify existing payload parsing still passes.**

Run the command above. Update fake responses to model `iter_content`, headers, and status codes; do not add real network access.

- [ ] **Step 5: Commit the HTTP policy slice.**

```powershell
git add src/agent/http_security.py src/agent/tools/http_tool.py src/agent/tools/__init__.py tests/test_http_tool.py tests/test_executor.py
git commit -m "fix: restrict agent HTTP egress"
```

### Task 4: Isolate and harden vector memory persistence

**Files:**
- Modify: `src/agent/vector_store.py`
- Modify: `src/agent/vector_memory.py`
- Modify: `src/agent/memory_manager.py`
- Modify: `src/agent/planner.py`
- Test: `tests/test_vector_memory.py`
- Test: `tests/test_memory_manager.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- `VectorStore.query(text: str, top_k: int = 3, user_id: Optional[str] = None) -> List[dict]` filters metadata before ranking when `user_id` is supplied.
- `VectorMemory.query` and `get_relevant_memory` expose the same optional user ID.
- Legacy records without `metadata.user_id` are treated as belonging to `default`.

- [ ] **Step 1: Write failing isolation and persistence tests.**

Add two users' documents with the same topic and assert each query returns only its own document. Add a legacy JSON fixture without user IDs and assert `user_id="default"` can retrieve it. Add a malformed-length fixture and assert `load` raises `ValueError`. Add a nested-path save test and assert the parent directory and file are created.

- [ ] **Step 2: Run memory tests and verify the new tests fail.**

Run:

```powershell
python -m pytest -q tests/test_vector_memory.py tests/test_memory_manager.py tests/test_planner.py
```

Expected: queries currently return both users' documents and persistence assumes the parent path already exists.

- [ ] **Step 3: Implement filtering, locking, validation, and atomic saves.**

Filter by normalized metadata owner before scoring. Protect store mutation and persistence with a re-entrant lock. Validate top-level lists and matching lengths on load, migrate absent vectors by embedding documents, and write JSON to a same-directory temporary file followed by `os.replace`. Make memory-enabled checks read the current environment consistently and pass `user_id` from Planner.

- [ ] **Step 4: Run focused memory tests and the complete non-server suite.**

Run the command above, then:

```powershell
python -m pytest -q --ignore=tests/test_server.py --ignore=tests/test_server_tools.py
```

- [ ] **Step 5: Commit the memory slice.**

```powershell
git add src/agent/vector_store.py src/agent/vector_memory.py src/agent/memory_manager.py src/agent/planner.py tests/test_vector_memory.py tests/test_memory_manager.py tests/test_planner.py
git commit -m "fix: isolate and atomically persist vector memory"
```

### Task 5: Make CI and Compose reproducible

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Create: `prometheus.yml`
- Test: `tests/test_deployment_config.py`

**Interfaces:**
- CI dependency installation fails the job when it fails.
- Compose includes a tracked Prometheus scrape configuration and uses a persistent `./data` directory for memory and audit logs.
- README documents `AGENT_AUTH_REQUIRED`, `AGENT_API_KEYS`, and `AGENT_HTTP_ALLOWED_HOSTS`.

- [ ] **Step 1: Write failing deployment configuration tests.**

Add tests that assert `prometheus.yml` exists, Compose references it, workflow YAML does not contain `pip install -r requirements.txt || true`, and README contains the new security environment variables.

- [ ] **Step 2: Run the deployment tests and verify they fail against the current checkout.**

Run:

```powershell
python -m pytest -q tests/test_deployment_config.py
```

Expected: the Prometheus file and security documentation assertions fail.

- [ ] **Step 3: Implement the configuration changes.**

Add a minimal scrape job targeting `agent:8000`. Remove the ignored install fallback from CI and release workflows. Change Compose volume mounts to `./data/vector_memory.json` and `./data/audit.log`, expose the authentication and HTTP policy environment variables, and document the required setup. Keep the health endpoint usable without a key.

- [ ] **Step 4: Run configuration tests and validate Compose syntax.**

Run:

```powershell
python -m pytest -q tests/test_deployment_config.py
docker compose config
```

Expected: both commands exit successfully.

- [ ] **Step 5: Commit the deployment slice.**

```powershell
git add .github/workflows/ci.yml .github/workflows/release.yml docker-compose.yml README.md prometheus.yml tests/test_deployment_config.py
git commit -m "chore: make CI and Compose reproducible"
```

### Task 6: Full verification and handoff

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the complete test suite.**

```powershell
python -m pytest -q
```

Expected: all tests pass with no collection errors.

- [ ] **Step 2: Run syntax and deployment checks.**

```powershell
python -m compileall -q src tests
docker compose config
git diff --check master...HEAD
```

- [ ] **Step 3: Update the changelog with the hardening and workflow changes.**

Add concise entries under `Unreleased` for ordered workflows, request authentication, HTTP egress restrictions, user-isolated memory, and reproducible deployment configuration.

- [ ] **Step 4: Review the final diff and status.**

```powershell
git diff master...HEAD --stat
git diff master...HEAD --check
git status --short --branch
```

Confirm only planned files changed and report any unavailable external checks separately from local test results.
