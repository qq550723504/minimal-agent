import threading
import time
from queue import Queue, Empty
from typing import Callable, Any


class TaskQueue:
    """一个简单的同步/异步任务队列实现。"""

    def __init__(self, worker_count: int = 1, poll_interval: float = 0.1):
        self._queue: Queue[tuple[Callable[..., Any], tuple, dict]] = Queue()
        self._worker_count = worker_count
        self._poll_interval = poll_interval
        self._workers: list[threading.Thread] = []
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        for _ in range(self._worker_count):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._workers.append(worker)
            worker.start()

    def stop(self):
        self._running = False
        for worker in self._workers:
            worker.join(timeout=1)

    def enqueue(self, func: Callable[..., Any], *args, **kwargs) -> None:
        self._queue.put((func, args, kwargs))

    def _worker_loop(self):
        while self._running:
            try:
                func, args, kwargs = self._queue.get(timeout=self._poll_interval)
                try:
                    func(*args, **kwargs)
                except Exception:
                    pass
                finally:
                    self._queue.task_done()
            except Empty:
                continue


QUEUE = TaskQueue(worker_count=2)


def start_queue():
    QUEUE.start()


def stop_queue():
    QUEUE.stop()


def enqueue_task(func: Callable[..., Any], *args, **kwargs) -> None:
    QUEUE.enqueue(func, *args, **kwargs)
