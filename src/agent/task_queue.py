import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Callable, Any, Dict, Optional, List

from src.agent.config import QUEUE_WORKER_COUNT

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    task_id: str
    owner_id: str = "default"
    status: str = "pending"
    attempts: int = 0
    max_retries: int = 0
    retry_delay: float = 0.0
    result: Any = None
    error: str = ""
    failed_step: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class TaskQueue:
    """一个支持重试与状态查询的任务队列实现。"""

    def __init__(self, worker_count: int = 1, poll_interval: float = 0.1):
        self._queue: Queue[tuple[str, Callable[..., Any], tuple, dict, int, float]] = Queue()
        self._worker_count = worker_count
        self._poll_interval = poll_interval
        self._workers: List[threading.Thread] = []
        self._running = False
        self._records: Dict[str, TaskRecord] = {}

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

    def enqueue(
        self,
        func: Callable[..., Any],
        *args,
        owner_id: str = "default",
        max_retries: int = 0,
        retry_delay: float = 0.0,
        **kwargs,
    ) -> str:
        task_id = uuid.uuid4().hex
        self._records[task_id] = TaskRecord(
            task_id=task_id,
            owner_id=owner_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        self._queue.put((task_id, func, args, kwargs, max_retries, retry_delay))
        return task_id

    def get_status(self, task_id: str, owner_id: Optional[str] = None) -> Optional[TaskRecord]:
        record = self._records.get(task_id)
        if record is None or (owner_id is not None and record.owner_id != owner_id):
            return None
        return record

    def list_tasks(self, status: Optional[str] = None, owner_id: Optional[str] = None) -> List[TaskRecord]:
        records = list(self._records.values())
        return [
            record
            for record in records
            if (status is None or record.status == status)
            and (owner_id is None or record.owner_id == owner_id)
        ]

    def _worker_loop(self):
        while self._running:
            try:
                task_id, func, args, kwargs, max_retries, retry_delay = self._queue.get(timeout=self._poll_interval)
                try:
                    self._process_task(task_id, func, args, kwargs, max_retries, retry_delay)
                finally:
                    self._queue.task_done()
            except Empty:
                continue

    def _process_task(
        self,
        task_id: str,
        func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        max_retries: int,
        retry_delay: float,
    ) -> None:
        record = self._records.get(task_id)
        if record is None:
            return

        record.status = "running"
        record.attempts += 1

        try:
            result = func(*args, **kwargs)
            record.result = result
            record.error = ""
            record.status = "completed"
            record.completed_at = time.time()
        except Exception as exc:
            record.error = repr(exc)
            record.failed_step = getattr(exc, "step_index", None)
            if record.attempts <= max_retries:
                record.status = "retrying"
                logger.warning(
                    "Task %s failed on attempt %s/%s: %s. Retrying after %.2fs",
                    task_id,
                    record.attempts,
                    max_retries,
                    exc,
                    retry_delay,
                )
                if retry_delay > 0:
                    time.sleep(retry_delay)
                self._queue.put((task_id, func, args, kwargs, max_retries, retry_delay))
            else:
                record.status = "failed"
                record.completed_at = time.time()
                logger.exception("Task %s failed after %s attempts", task_id, record.attempts)


QUEUE = TaskQueue(worker_count=QUEUE_WORKER_COUNT)


def start_queue():
    QUEUE.start()


def stop_queue():
    QUEUE.stop()


def enqueue_task(func: Callable[..., Any], *args, **kwargs) -> str:
    return QUEUE.enqueue(func, *args, **kwargs)


def get_status(task_id: str, owner_id: Optional[str] = None) -> Optional[TaskRecord]:
    return QUEUE.get_status(task_id, owner_id=owner_id)


def list_tasks(status: Optional[str] = None, owner_id: Optional[str] = None) -> List[TaskRecord]:
    return QUEUE.list_tasks(status, owner_id=owner_id)
