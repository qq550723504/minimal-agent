import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Callable, Any, Dict, Optional, List

from src.agent.config import QUEUE_WORKER_COUNT
from src.agent.workflow_store import WorkflowStore

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

    def __init__(
        self,
        worker_count: int = 1,
        poll_interval: float = 0.1,
        workflow_store: Optional[WorkflowStore] = None,
    ):
        if worker_count <= 0:
            raise ValueError("worker_count must be positive")
        self._queue: Queue[tuple] = Queue()
        self._worker_count = worker_count
        self._poll_interval = poll_interval
        self._workers: List[threading.Thread] = []
        self._running = False
        self._records: Dict[str, TaskRecord] = {}
        self._lock = threading.RLock()
        self._workflow_store = workflow_store
        self._queued_workflows: set[str] = set()

    def start(self):
        if self._running:
            return
        if self._workflow_store is not None:
            self.recover_workflows()
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
        with self._lock:
            self._records[task_id] = TaskRecord(
                task_id=task_id,
                owner_id=owner_id,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            self._queue.put(
                ("callable", task_id, func, args, kwargs, max_retries, retry_delay)
            )
        return task_id

    def enqueue_workflow(self, workflow_id: str) -> None:
        if self._workflow_store is None:
            raise RuntimeError("workflow store is not configured")
        with self._lock:
            record = self._workflow_store.get_workflow(workflow_id)
            if record is None:
                raise KeyError(f"workflow not found: {workflow_id}")
            if record["status"] in ("completed", "failed"):
                return
            if workflow_id in self._queued_workflows:
                return
            self._queued_workflows.add(workflow_id)
            self._queue.put(("workflow", workflow_id))

    def recover_workflows(self) -> int:
        if self._workflow_store is None:
            return 0
        self._workflow_store.mark_interrupted_workflows_pending()
        queued = 0
        for workflow_id in self._workflow_store.list_recoverable_workflows():
            with self._lock:
                already_queued = workflow_id in self._queued_workflows
            self.enqueue_workflow(workflow_id)
            if not already_queued:
                queued += 1
        return queued

    def _release_workflow(self, workflow_id: str) -> None:
        with self._lock:
            self._queued_workflows.discard(workflow_id)

    def get_status(self, task_id: str, owner_id: Optional[str] = None) -> Optional[TaskRecord]:
        with self._lock:
            record = self._records.get(task_id)
            if record is not None:
                if owner_id is not None and record.owner_id != owner_id:
                    return None
                return record
        if self._workflow_store is None:
            return None
        workflow = self._workflow_store.get_workflow(task_id, owner_id=owner_id)
        return self._task_record_from_workflow(workflow) if workflow is not None else None

    def list_tasks(self, status: Optional[str] = None, owner_id: Optional[str] = None) -> List[TaskRecord]:
        with self._lock:
            records = list(self._records.values())
        result = [
            record
            for record in records
            if (status is None or record.status == status)
            and (owner_id is None or record.owner_id == owner_id)
        ]
        if self._workflow_store is not None:
            result.extend(
                self._task_record_from_workflow(workflow)
                for workflow in self._workflow_store.list_workflows(
                    status=status,
                    owner_id=owner_id,
                )
            )
        return result

    @staticmethod
    def _task_record_from_workflow(workflow: dict[str, Any]) -> TaskRecord:
        return TaskRecord(
            task_id=workflow["workflow_id"],
            owner_id=workflow["owner_id"],
            status=workflow["status"],
            attempts=workflow["attempts"],
            max_retries=workflow["max_retries"],
            retry_delay=workflow["retry_delay"],
            result=workflow["results"],
            error=workflow["error"],
            failed_step=workflow["failed_step"],
            created_at=workflow["created_at"],
            completed_at=workflow["completed_at"],
        )

    def _worker_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=self._poll_interval)
                try:
                    if item[0] == "workflow":
                        self._process_workflow(item[1])
                    else:
                        self._process_task(*item[1:])
                finally:
                    self._queue.task_done()
            except Empty:
                continue

    def _process_workflow(self, workflow_id: str) -> None:
        if self._workflow_store is None:
            self._release_workflow(workflow_id)
            return

        from src.agent.executor import DurableWorkflowRunner, WorkflowExecutionError

        retry = False
        try:
            result = DurableWorkflowRunner(self._workflow_store, workflow_id)()
            logger.debug("Workflow %s completed with %s results", workflow_id, len(result))
        except WorkflowExecutionError as exc:
            workflow = self._workflow_store.get_workflow(workflow_id)
            if workflow is None:
                logger.error("Workflow %s disappeared while executing", workflow_id)
                return
            if workflow["attempts"] <= workflow["max_retries"]:
                self._workflow_store.retry_workflow(
                    workflow_id,
                    repr(exc.cause),
                    exc.step_index,
                )
                retry = True
                self._release_workflow(workflow_id)
                if workflow["retry_delay"] > 0:
                    time.sleep(workflow["retry_delay"])
                self.enqueue_workflow(workflow_id)
            else:
                self._workflow_store.fail_workflow(
                    workflow_id,
                    repr(exc.cause),
                    exc.step_index,
                    exc.completed_results,
                )
        except Exception as exc:
            workflow = self._workflow_store.get_workflow(workflow_id)
            if workflow is not None:
                self._workflow_store.fail_workflow(
                    workflow_id,
                    repr(exc),
                    getattr(exc, "step_index", None),
                    workflow["results"],
                )
            else:
                logger.exception("Workflow %s failed without a persisted record", workflow_id)
        finally:
            if not retry:
                self._release_workflow(workflow_id)

    def _process_task(
        self,
        task_id: str,
        func: Callable[..., Any],
        args: tuple,
        kwargs: dict,
        max_retries: int,
        retry_delay: float,
    ) -> None:
        with self._lock:
            record = self._records.get(task_id)
        if record is None:
            return

        with self._lock:
            record.status = "running"
            record.attempts += 1

        try:
            result = func(*args, **kwargs)
            with self._lock:
                record.result = result
                record.error = ""
                record.failed_step = None
                record.status = "completed"
                record.completed_at = time.time()
        except Exception as exc:
            with self._lock:
                record.error = repr(exc)
                record.failed_step = getattr(exc, "step_index", None)
                should_retry = record.attempts <= max_retries
                if should_retry:
                    record.status = "retrying"
            if should_retry:
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
                self._queue.put(
                    ("callable", task_id, func, args, kwargs, max_retries, retry_delay)
                )
            else:
                with self._lock:
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
