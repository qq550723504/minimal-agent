# Persistent Workflow State Design

## Goal

Make queued Agent workflows survive process restarts while preserving the current public API, ordered execution semantics, owner isolation, retry behavior, and existing synchronous task execution.

## Scope

This slice makes workflows created through `enqueue_task_execution()` durable. It stores the workflow definition, per-step state, task metadata, attempts, results, and failure information in SQLite. On queue startup, interrupted workflows are recovered and resumed from the first incomplete step.

The existing generic `TaskQueue.enqueue(callable, ...)` API remains supported for in-process tasks and existing callers. Arbitrary Python callables are not serialized or reconstructed across a process restart; only the workflow path is restartable in this slice.

Out of scope: cancellation, timeouts, idempotency keys, compensation transactions, DAG dependencies, human approval, distributed workers, and a UI.

## Design

### Storage

Add `src/agent/workflow_store.py`, backed by Python's standard-library `sqlite3` module. The store owns schema creation, transactions, row conversion, and recovery queries; queue and executor code must not issue SQL directly.

The database path is configured by `WORKFLOW_STORE_PATH`, defaulting to `data/workflows.sqlite3`. Parent directories are created by the store. SQLite uses WAL mode and foreign keys. Tests pass a temporary path explicitly.

The schema has three tables:

- `workflows`: one row per queued workflow, including `workflow_id`, `owner_id`, status, retry settings, attempt count, serialized aggregate result, error, failed step, and timestamps.
- `workflow_steps`: one row per input step, including its index, JSON definition, status, attempt count, result, error, and completion timestamp.
- `workflow_events`: append-only lifecycle records for enqueue, start, step completion, retry, failure, and completion, containing workflow ID, event type, step index when applicable, and event timestamp.

Workflow and step mutations happen in one transaction so task status cannot claim a step completed before its result is stored. Results and step definitions are JSON encoded with UTF-8 and must remain compatible with the current `Any` step contract.

### Execution and recovery

`enqueue_task_execution()` creates the workflow and all step rows before placing a lightweight workflow reference on the queue. The returned `task_id` remains the workflow ID, and the existing response shape is unchanged.

The durable runner loads the workflow by ID, finds the first step whose status is not `completed`, executes steps in order, and commits each successful step before continuing. A workflow with no steps completes with an empty result list.

When starting, the queue marks stale `running` workflows as `pending`, then enqueues all `pending` and `retrying` workflows. A restart therefore re-executes only the current incomplete step. A step that was executing when the process stopped is treated as incomplete and may run again; exactly-once execution is explicitly not promised until the later idempotency slice.

Workflow-level exceptions preserve the current `WorkflowExecutionError` contract. The store records `failed_step`, the serialized partial results, and the terminal status after retries are exhausted. Retry attempts update the same workflow row and append events instead of creating a new task ID.

### Queue integration

Extend `TaskQueue` with an optional workflow store and a `enqueue_workflow(workflow_id)` method. The existing callable queue path continues to use `TaskRecord` in memory. The global queue is initialized with the configured SQLite store and recovers durable workflows when `start_queue()` is called.

The queue uses a lock around in-memory record access and store-backed status transitions. `get_status()` and `list_tasks()` return the current durable workflow state for workflow IDs and retain current owner filtering. Missing or unauthorized IDs continue to appear as not found to the API.

### API and configuration

No endpoint shape changes are required. `/api/handle/queue`, `/api/tasks/{task_id}`, and `/api/tasks` continue using the existing response model. Documentation adds `WORKFLOW_STORE_PATH`, the restart/retry semantics, and the limitation that arbitrary callable tasks are not durable.

## Error handling

- Invalid or unreadable workflow JSON prevents enqueue and returns the existing client error path.
- SQLite failures are logged and fail the enqueue operation; no in-memory task ID is returned for a workflow that was not persisted.
- A missing workflow referenced by a queue item is recorded as failed rather than silently dropped.
- Recovery is idempotent: repeated startup recovery does not create duplicate workflow records or duplicate task IDs.
- Owner checks are applied to persisted records before returning status or task lists.

## Testing

Add tests for:

1. Schema creation and workflow round-trip persistence.
2. A two-step workflow producing one durable task ID and ordered committed step results.
3. Recovery of a workflow interrupted after step one without repeating step one.
4. Retry and terminal failure persistence, including `failed_step` and partial results.
5. Owner isolation through the existing task status/list APIs.
6. Queue startup recovery and duplicate-recovery protection.
7. Existing synchronous execution and generic queue compatibility.

The focused tests must fail before implementation. The full suite must remain green after implementation.

## Rollout and migration

SQLite creates its schema automatically on first startup. Existing in-memory tasks cannot be migrated because their callable and state are not persisted; they complete or disappear under the old process lifecycle. Existing API clients require no changes. The new database file is runtime data and must be included in the existing `data/` persistence volume for Docker deployments.
