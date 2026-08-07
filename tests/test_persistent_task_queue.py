import time

from src.agent.task_queue import TaskQueue
from src.agent.tool_registry import register_tool
from src.agent.workflow_store import WorkflowStore


def _wait_for_workflow(store, workflow_id, status, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = store.get_workflow(workflow_id)
        if record and record["status"] == status:
            return record
        time.sleep(0.01)
    return store.get_workflow(workflow_id)


def test_queue_startup_recovers_without_repeating_completed_steps(tmp_path):
    calls = []

    def record(payload):
        calls.append(payload)
        return payload

    register_tool("test_queue_recovery", record)
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow(
        "wf-1",
        "alice",
        ["test_queue_recovery: first", "test_queue_recovery: second"],
        0,
        0.0,
    )
    store.start_workflow("wf-1")
    store.start_step("wf-1", 0)
    store.complete_step("wf-1", 0, "first", ["first"])

    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)
    queue.start()
    record = _wait_for_workflow(store, "wf-1", "completed")
    queue.stop()

    assert record["status"] == "completed"
    assert calls == ["second"]
    assert record["results"] == ["first", "second"]


def test_recovery_does_not_enqueue_same_workflow_twice(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first"], 0, 0.0)
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)

    assert queue.recover_workflows() == 1
    assert queue.recover_workflows() == 0


def test_new_queue_reads_persisted_workflow_status(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first"], 0, 0.0)
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)
    queue.enqueue_workflow("wf-1")
    queue.start()
    _wait_for_workflow(store, "wf-1", "completed")
    queue.stop()

    reopened_queue = TaskQueue(
        worker_count=1,
        poll_interval=0.01,
        workflow_store=WorkflowStore(str(tmp_path / "workflows.sqlite3")),
    )
    record = reopened_queue.get_status("wf-1", owner_id="alice")

    assert record is not None
    assert record.status == "completed"
    assert record.result == ["first"]
    assert reopened_queue.get_status("wf-1", owner_id="bob") is None
