import time

from src.agent.application.execution.service import WorkflowRunner, execute_workflow
from src.agent.infrastructure.workflows.task_queue import TaskQueue


def test_enqueue_and_execute_task():
    results = []

    def add_result(item):
        results.append(item)

    queue = TaskQueue(worker_count=1, poll_interval=0.01)
    queue.start()
    queue.enqueue(add_result, "hello")
    time.sleep(0.2)
    queue.stop()

    assert results == ["hello"]


def test_task_queue_retries_and_status():
    states = {"attempts": 0, "executed": False}

    def flaky(item):
        states["attempts"] += 1
        if states["attempts"] == 1:
            raise ValueError("temporary failure")
        states["executed"] = True
        return item

    queue = TaskQueue(worker_count=1, poll_interval=0.01)
    queue.start()
    task_id = queue.enqueue(flaky, "hello", max_retries=1, retry_delay=0.01)
    time.sleep(0.3)
    queue.stop()

    record = queue.get_status(task_id)
    assert record is not None
    assert record.status == "completed"
    assert record.attempts == 2
    assert record.result == "hello"
    assert record.error == ""
    assert states["executed"] is True


def test_task_queue_runs_workflow_in_order_with_multiple_workers():
    events = []

    queue = TaskQueue(worker_count=2, poll_interval=0.01)
    queue.start()
    task_id = queue.enqueue(execute_workflow, ["echo: first", "echo: second"])

    deadline = time.time() + 1
    while time.time() < deadline:
        record = queue.get_status(task_id)
        if record and record.status == "completed":
            break
        time.sleep(0.01)
    queue.stop()

    record = queue.get_status(task_id)
    assert record is not None
    assert record.status == "completed"
    assert record.result == ["first", "second"]
    assert record.owner_id == "default"


def test_task_queue_records_workflow_failed_step():
    def fail(_payload):
        raise RuntimeError("boom")

    from src.agent.tool_registry import register_tool

    register_tool("test_queue_failure", fail)
    queue = TaskQueue(worker_count=1, poll_interval=0.01)
    queue.start()
    task_id = queue.enqueue(execute_workflow, ["echo: first", "test_queue_failure: second"])

    deadline = time.time() + 1
    while time.time() < deadline:
        record = queue.get_status(task_id)
        if record and record.status == "failed":
            break
        time.sleep(0.01)
    queue.stop()

    record = queue.get_status(task_id)
    assert record is not None
    assert record.status == "failed"
    assert record.failed_step == 1


def test_workflow_retry_does_not_repeat_completed_steps():
    calls = []
    state = {"second": 0}

    def record(payload):
        calls.append(payload)
        if payload == "second":
            state["second"] += 1
            if state["second"] == 1:
                raise RuntimeError("temporary failure")
        return payload

    from src.agent.tool_registry import register_tool

    register_tool("test_retry_resume", record)
    runner = WorkflowRunner(["test_retry_resume: first", "test_retry_resume: second"])
    queue = TaskQueue(worker_count=1, poll_interval=0.01)
    queue.start()
    task_id = queue.enqueue(runner, max_retries=1, retry_delay=0.01)

    deadline = time.time() + 1
    while time.time() < deadline:
        record = queue.get_status(task_id)
        if record and record.status == "completed":
            break
        time.sleep(0.01)
    queue.stop()

    record = queue.get_status(task_id)
    assert record is not None
    assert record.status == "completed"
    assert record.result == ["first", "second"]
    assert calls == ["first", "second", "second"]
    assert record.failed_step is None


def test_task_queue_rejects_nonpositive_worker_count():
    import pytest

    with pytest.raises(ValueError, match="worker_count"):
        TaskQueue(worker_count=0)


def test_task_queue_filters_status_by_owner():
    queue = TaskQueue(worker_count=1, poll_interval=0.01)
    alice_task = queue.enqueue(lambda: "alice", owner_id="alice")
    bob_task = queue.enqueue(lambda: "bob", owner_id="bob")

    assert queue.get_status(alice_task, owner_id="bob") is None
    assert queue.get_status(alice_task, owner_id="alice").owner_id == "alice"
    assert [record.task_id for record in queue.list_tasks(owner_id="bob")] == [bob_task]
