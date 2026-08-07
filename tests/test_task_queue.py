import time

from src.agent.executor import execute_workflow
from src.agent.task_queue import TaskQueue


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
