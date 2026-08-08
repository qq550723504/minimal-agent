# Persistent Workflow State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended for inline execution) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist queued workflows and per-step state in SQLite so workflows can resume after process restarts without changing the current task API.

**Architecture:** Add a SQLite-backed `WorkflowStore` that owns schema and transactions. Make `enqueue_task_execution()` create a durable workflow and enqueue only its ID; a durable runner loads the first incomplete step, commits each step result, and updates the existing task record. Keep generic callable queue tasks in memory for backward compatibility, while the global queue recovers durable workflows at startup.

**Tech Stack:** Python 3.10+, standard-library `sqlite3`, `threading`, `json`, FastAPI, pytest, temporary SQLite databases.

## Global Constraints

- Do not add a third-party database dependency.
- Preserve the existing `/api/handle/queue`, `/api/tasks/{task_id}`, and `/api/tasks` response shapes.
- Preserve synchronous `execute_tasks()` and generic `TaskQueue.enqueue()` behavior.
- Workflow execution remains ordered and at-least-once across restarts; exactly-once execution is out of scope.
- Apply owner filtering to every persisted workflow read.
- Every production change must have a failing test first, then a focused green run, then the full suite.
- Keep existing unrelated files and working-tree changes untouched.

---

### Task 1: Add the SQLite workflow store

**Files:**
- Create: `src/agent/workflow_store.py`
- Create: `tests/test_workflow_store.py`

**Interfaces:**
- `WorkflowStore(path: str)` creates the parent directory, opens SQLite, enables foreign keys and WAL, and creates the schema.
- `create_workflow(workflow_id: str, owner_id: str, steps: list[Any], max_retries: int, retry_delay: float) -> None` persists one workflow and its ordered steps atomically.
- `get_workflow(workflow_id: str, owner_id: str | None = None) -> dict | None` returns workflow metadata plus ordered step records, or `None` for a missing/unauthorized workflow.
- `list_workflows(status: str | None = None, owner_id: str | None = None) -> list[dict]` returns durable workflow records.
- `mark_interrupted_workflows_pending() -> int` changes `running` workflows to `pending` and returns the count.
- `list_recoverable_workflows() -> list[str]` returns unique IDs in `pending` or `retrying` state.
- `start_workflow(workflow_id: str) -> None`, `start_step(workflow_id: str, step_index: int) -> None`, `complete_step(workflow_id: str, step_index: int, result: str, results: list[str]) -> None`, `retry_workflow(workflow_id: str, error: str, failed_step: int | None) -> None`, `fail_workflow(workflow_id: str, error: str, failed_step: int | None, results: list[str]) -> None`, and `complete_workflow(workflow_id: str, results: list[str]) -> None` update state and append lifecycle events transactionally.

- [ ] **Step 1: Write the failing persistence tests.**

Add tests that create a store at `tmp_path / "workflows.sqlite3"`, persist a two-step workflow containing both a string and a dict, reopen the store, and assert owner, retry settings, ordered JSON step values, and initial `pending` state. Add a test that unauthorized `get_workflow()` and `list_workflows()` return no records. Add a test that step completion stores its result and aggregate results atomically.

```python
def test_workflow_round_trip_survives_reopen(tmp_path):
    path = tmp_path / "workflows.sqlite3"
    store = WorkflowStore(str(path))
    store.create_workflow("wf-1", "alice", ["echo: first", {"tool": "echo", "payload": "second"}], 2, 0.25)

    reopened = WorkflowStore(str(path))
    record = reopened.get_workflow("wf-1", owner_id="alice")

    assert record["status"] == "pending"
    assert [step["definition"] for step in record["steps"]] == ["echo: first", {"tool": "echo", "payload": "second"}]
    assert reopened.get_workflow("wf-1", owner_id="bob") is None
```

- [ ] **Step 2: Run the focused tests and verify they fail for the missing store.**

Run: `python -m pytest -q tests/test_workflow_store.py`

Expected: collection fails because `src.agent.workflow_store` does not exist.

- [ ] **Step 3: Implement the minimal schema and store methods.**

Use three tables named `workflows`, `workflow_steps`, and `workflow_events`. Store step definitions and results with `json.dumps(..., ensure_ascii=False)` and decode them in row conversion. Use a single connection per store protected by `threading.RLock`; wrap each public mutation in `with connection:` so workflow and event changes commit together. Add a unique `(workflow_id, step_index)` constraint and `ON DELETE CASCADE` foreign keys. Represent timestamps as `time.time()` floats and event payloads as JSON.

- [ ] **Step 4: Run the focused store tests.**

Run: `python -m pytest -q tests/test_workflow_store.py`

Expected: all store tests pass.

- [ ] **Step 5: Commit the store slice.**

```powershell
git add src\agent\workflow_store.py tests\test_workflow_store.py
git commit -m "feat: add persistent workflow store"
```

### Task 2: Make workflow execution durable and resumable

**Files:**
- Modify: `src/agent/executor.py`
- Create: `tests/test_persistent_executor.py`

**Interfaces:**
- `DurableWorkflowRunner(store: WorkflowStore, workflow_id: str)` is callable and returns `list[str]`.
- `enqueue_task_execution(steps, owner_id="default", max_retries=0, retry_delay=0.0)` persists the workflow before enqueueing it and returns the current `{"status": "queued", "task_id": id, "task_ids": [id]}` shape.

- [ ] **Step 1: Write the failing durable-execution tests.**

Add a test using a temporary store and a registered test tool that records calls. Enqueue a two-step workflow, invoke `DurableWorkflowRunner`, reopen the store, and assert both steps are completed in order and the aggregate result is persisted. Add an interruption test that manually marks step zero completed, constructs a new runner, and asserts only step one executes. Add a failure test asserting the store records `failed_step` and completed partial results.

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `python -m pytest -q tests/test_persistent_executor.py`

Expected: import or attribute failures because the durable runner and persisted enqueue path do not exist.

- [ ] **Step 3: Implement the durable runner and enqueue path.**

Generate the workflow ID before persistence. Construct `WorkflowStore` from the configured global store only at the integration boundary, call `create_workflow()` before queue insertion, and raise the storage error without returning a task ID if persistence fails. In the runner, load steps, skip `completed` rows, call `execute_step()`, commit each successful step, and translate execution failures into the existing `WorkflowExecutionError` while updating store state. Keep `execute_workflow()` and `WorkflowRunner` unchanged for existing in-memory callers.

- [ ] **Step 4: Run focused executor and existing executor tests.**

Run: `python -m pytest -q tests/test_persistent_executor.py tests/test_executor.py`

Expected: all focused and existing executor tests pass.

- [ ] **Step 5: Commit the durable executor slice.**

```powershell
git add src\agent\executor.py tests\test_persistent_executor.py
git commit -m "feat: persist queued workflows before execution"
```

### Task 3: Recover durable workflows in the task queue

**Files:**
- Modify: `src/agent/task_queue.py`
- Modify: `tests/test_task_queue.py`
- Create: `tests/test_persistent_task_queue.py`

**Interfaces:**
- `TaskQueue(worker_count=1, poll_interval=0.1, workflow_store: WorkflowStore | None = None)` retains current constructor compatibility.
- `TaskQueue.enqueue_workflow(workflow_id: str) -> None` places a durable workflow reference on the queue without creating a second workflow record.
- `TaskQueue.recover_workflows() -> int` marks interrupted workflows pending and enqueues each recoverable ID once.

- [ ] **Step 1: Write failing recovery and concurrency tests.**

Add a restart test that creates a workflow, marks it `running`, calls `recover_workflows()` on a new queue, and asserts it becomes pending and is enqueued exactly once. Add a test that runs a recovered workflow and verifies a completed step is not repeated. Add a status/list test that reads persisted records after the original queue object is gone. Extend existing queue tests to assert generic callable tasks still work.

- [ ] **Step 2: Run the focused queue tests and verify the new cases fail.**

Run: `python -m pytest -q tests/test_persistent_task_queue.py tests/test_task_queue.py`

Expected: new recovery tests fail because the queue has no workflow store or recovery path; existing tests remain green.

- [ ] **Step 3: Implement queue persistence and recovery.**

Add an `RLock` around `_records` access. Keep the existing callable tuple path and add a durable workflow tuple path that invokes `DurableWorkflowRunner`. On `start()`, call `recover_workflows()` before worker threads begin consuming. Use a set of queued workflow IDs to prevent duplicate recovery enqueues. For durable IDs, `get_status()` and `list_tasks()` convert store records into `TaskRecord`-compatible objects while applying owner filters. Record missing workflow references as terminal failures instead of dropping them.

- [ ] **Step 4: Run focused queue tests and the full suite.**

Run: `python -m pytest -q tests/test_persistent_task_queue.py tests/test_task_queue.py tests/test_executor.py`

Expected: all selected tests pass; then run `python -m pytest -q` and expect the original suite plus new tests to pass.

- [ ] **Step 5: Commit the queue slice.**

```powershell
git add src\agent\task_queue.py tests\test_task_queue.py tests\test_persistent_task_queue.py
git commit -m "feat: recover persisted workflows on queue startup"
```

### Task 4: Wire configuration, API reads, Docker persistence, and documentation

**Files:**
- Modify: `src/agent/config.py`
- Modify: `src/agent/task_queue.py`
- Modify: `src/agent/server.py`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `docs/AGENT_GUIDE.md`
- Modify: `tests/test_deployment_config.py`
- Create: `tests/test_persistent_api.py`

**Interfaces:**
- `WORKFLOW_STORE_PATH` defaults to `data/workflows.sqlite3` and is used by the global queue.
- Existing task endpoints return the persisted workflow state through the existing `TaskStatusOut` fields.

- [ ] **Step 1: Write failing configuration and API tests.**

Add a config test that sets `WORKFLOW_STORE_PATH` before importing config in a subprocess or reloads the module and asserts the configured path. Add an API test that persists a workflow, queries `/api/tasks/{task_id}` as the owner, and asserts a different owner receives 404. Add a deployment test that asserts Compose mounts `./data` to `/app/data` and documents `WORKFLOW_STORE_PATH`.

- [ ] **Step 2: Run the focused tests and verify the new cases fail.**

Run: `python -m pytest -q tests/test_persistent_api.py tests/test_deployment_config.py`

Expected: new assertions fail because the setting, durable queue wiring, or documentation is absent.

- [ ] **Step 3: Wire the configured store and update docs.**

Read `WORKFLOW_STORE_PATH` in `config.py`, create one global `WorkflowStore`, inject it into the global `TaskQueue`, and ensure startup recovery runs before API requests are served. Keep endpoint models unchanged. Update Compose and both docs with the path, volume requirement, restart behavior, and non-durable generic callable limitation.

- [ ] **Step 4: Run API, deployment, and full tests.**

Run: `python -m pytest -q tests/test_persistent_api.py tests/test_deployment_config.py tests/test_server.py tests/test_server_tools.py`; then run `python -m pytest -q`.

Expected: all tests pass. Existing FastAPI and Starlette deprecation warnings may remain and should be reported separately rather than mixed into this slice.

- [ ] **Step 5: Commit the integration slice.**

```powershell
git add src\agent\config.py src\agent\task_queue.py src\agent\server.py docker-compose.yml README.md docs\AGENT_GUIDE.md tests\test_deployment_config.py tests\test_persistent_api.py
git commit -m "feat: configure durable workflow persistence"
```

### Task 5: Final verification and handoff

**Files:**
- Modify: `CHANGELOG.md`
- Test: entire `tests/` suite

- [ ] **Step 1: Add an Unreleased changelog entry.**

Document SQLite workflow persistence, restart recovery from the first incomplete step, owner filtering, and the at-least-once limitation.

- [ ] **Step 2: Run the complete verification set.**

Run: `python -m pytest -q`; inspect `git diff --check`; inspect `git status --short`; confirm only intended files are changed.

- [ ] **Step 3: Review the diff against the spec.**

Confirm every schema, recovery, API compatibility, error-handling, and testing requirement in `docs/superpowers/specs/2026-08-08-persistent-workflow-state-design.md` has corresponding code or test coverage.

- [ ] **Step 4: Commit the release notes.**

```powershell
git add CHANGELOG.md
git commit -m "docs: note persistent workflow state"
```
