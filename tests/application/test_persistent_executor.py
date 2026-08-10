import pytest

from src.agent.application.execution.service import DurableWorkflowRunner, WorkflowExecutionError, enqueue_task_execution
from src.agent.infrastructure.workflows.task_queue import TaskQueue
from src.agent.tool_registry import register_tool
from src.agent.infrastructure.workflows.workflow_store import WorkflowStore


def test_durable_runner_commits_steps_in_order(tmp_path):
    calls = []

    def record(payload):
        calls.append(payload)
        return payload

    register_tool("test_durable_order", record)
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow(
        "wf-1",
        "alice",
        ["test_durable_order: first", "test_durable_order: second"],
        0,
        0.0,
    )

    result = DurableWorkflowRunner(store, "wf-1")()

    assert result == ["first", "second"]
    assert calls == ["first", "second"]
    record = store.get_workflow("wf-1", owner_id="alice")
    assert record["status"] == "completed"
    assert [step["status"] for step in record["steps"]] == ["completed", "completed"]
    assert record["results"] == ["first", "second"]


def test_durable_runner_resumes_after_completed_step(tmp_path):
    calls = []

    def record(payload):
        calls.append(payload)
        return payload

    register_tool("test_durable_resume", record)
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow(
        "wf-1",
        "alice",
        ["test_durable_resume: first", "test_durable_resume: second"],
        0,
        0.0,
    )
    store.start_workflow("wf-1")
    store.start_step("wf-1", 0)
    store.complete_step("wf-1", 0, "first", ["first"])

    result = DurableWorkflowRunner(store, "wf-1")()

    assert result == ["first", "second"]
    assert calls == ["second"]


def test_enqueue_persists_before_placing_durable_runner_on_queue(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)

    result = enqueue_task_execution(
        ["echo: first", "echo: second"],
        owner_id="alice",
        workflow_store=store,
        workflow_queue=queue,
    )

    task_id = result["task_id"]
    assert result == {"status": "queued", "task_id": task_id, "task_ids": [task_id]}
    assert store.get_workflow(task_id, owner_id="alice")["status"] == "pending"
    assert queue.get_status(task_id, owner_id="alice").status == "pending"


def test_enqueue_returns_persisted_id_and_uses_durable_queue(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)

    result = enqueue_task_execution(
        ["echo: first"],
        owner_id="alice",
        workflow_store=store,
        workflow_queue=queue,
    )

    task_id = result["task_id"]
    assert task_id == result["task_ids"][0]
    assert store.get_workflow(task_id, owner_id="alice") is not None
    assert queue.get_status(task_id, owner_id="alice").status == "pending"


def test_durable_runner_reports_failed_step(tmp_path):
    def fail(_payload):
        raise RuntimeError("boom")

    register_tool("test_durable_failure", fail)
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow(
        "wf-1",
        "alice",
        ["echo: first", "test_durable_failure: second"],
        0,
        0.0,
    )

    with pytest.raises(WorkflowExecutionError) as raised:
        DurableWorkflowRunner(store, "wf-1")()

    assert raised.value.step_index == 1
    assert raised.value.completed_results == ["first"]
