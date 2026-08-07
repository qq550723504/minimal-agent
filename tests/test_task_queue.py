import time

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
