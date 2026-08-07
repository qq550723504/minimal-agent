import pytest

from src.agent.executor import DurableWorkflowRunner, WorkflowExecutionError, enqueue_task_execution
from src.agent.tool_registry import register_tool
from src.agent.workflow_store import WorkflowStore


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


def test_enqueue_persists_before_placing_durable_runner_on_queue(tmp_path, monkeypatch):
    calls = []
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))

    def fake_enqueue(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return func.workflow_id

    monkeypatch.setattr("src.agent.executor.enqueue_task", fake_enqueue)

    result = enqueue_task_execution(
        ["echo: first", "echo: second"],
        owner_id="alice",
        workflow_store=store,
    )

    task_id = result["task_id"]
    assert result == {"status": "queued", "task_id": task_id, "task_ids": [task_id]}
    assert store.get_workflow(task_id, owner_id="alice")["status"] == "pending"
    assert len(calls) == 1
    assert isinstance(calls[0][0], DurableWorkflowRunner)
    assert calls[0][0].workflow_id == task_id
    assert calls[0][2]["owner_id"] == "alice"


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
