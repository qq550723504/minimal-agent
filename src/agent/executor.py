import json
import re
import uuid
from typing import Any, List, Optional

from src.agent.task_queue import enqueue_task
from src.agent.tool_registry import get_tool
from src.agent.workflow_store import WorkflowStore

# 导入默认工具注册模块
import src.agent.tools  # noqa: F401


class WorkflowExecutionError(RuntimeError):
    def __init__(self, step_index: int, cause: Exception, completed_results=None):
        self.step_index = step_index
        self.cause = cause
        self.completed_results = list(completed_results or [])
        super().__init__(f"workflow step {step_index} failed: {cause}")


def _invoke_tool(tool_name: str, payload: str) -> str:
    tool = get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return tool(payload)


def execute_tool_step(step: str) -> str:
    """执行通用工具步骤。"""
    if not step:
        raise ValueError("tool step is empty")

    parts = step.split(" ", 1)
    tool_name = parts[0].strip().lower().rstrip(":")
    payload = parts[1].strip() if len(parts) > 1 else ""
    return _invoke_tool(tool_name, payload)


def execute_step(step: Any) -> str:
    """执行单条步骤。"""
    if isinstance(step, dict):
        tool_name = step.get("tool")
        if isinstance(tool_name, str):
            payload = step.get("payload", "")
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            return _invoke_tool(tool_name, payload)

        action = step.get("action") or step.get("text") or step.get("step")
        if isinstance(action, str):
            return execute_step(action)
        return json.dumps(step, ensure_ascii=False)

    if not isinstance(step, str):
        return json.dumps(step, ensure_ascii=False)

    text = step.strip()
    if text.startswith("echo: "):
        return text.replace("echo: ", "", 1)

    matcher = re.match(r"^(?P<tool>[A-Za-z0-9_]+):?\s*(?P<payload>.*)$", text)
    if matcher:
        tool_name = matcher.group("tool").lower()
        if get_tool(tool_name):
            return execute_tool_step(text)

    return text


def execute_tasks(steps: List[Any]) -> List[str]:
    """同步执行步骤列表。"""
    return [execute_step(step) for step in steps]


class DurableWorkflowRunner:
    """从 SQLite 状态执行 workflow，并跳过已经完成的步骤。"""

    def __init__(self, store: WorkflowStore, workflow_id: str):
        self.store = store
        self.workflow_id = workflow_id
        self.__name__ = "execute_workflow"

    def __call__(self) -> List[str]:
        record = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise KeyError(f"workflow not found: {self.workflow_id}")
        if record["status"] == "completed":
            return list(record["results"])

        self.store.start_workflow(self.workflow_id)
        results: List[str] = []
        for step_record in record["steps"]:
            step_index = step_record["step_index"]
            if step_record["status"] == "completed":
                results.append(step_record["result"])
                continue

            try:
                self.store.start_step(self.workflow_id, step_index)
                result = execute_step(step_record["definition"])
            except Exception as exc:
                raise WorkflowExecutionError(step_index, exc, results) from exc

            results.append(result)
            self.store.complete_step(self.workflow_id, step_index, result, results)

        self.store.complete_workflow(self.workflow_id, results)
        return list(results)


class WorkflowRunner:
    """执行 workflow，并在队列重试时从失败步骤继续。"""

    def __init__(self, steps: List[Any]):
        self.steps = list(steps)
        self.results: List[str] = []
        self.next_step = 0
        self.__name__ = "execute_workflow"

    def __call__(self) -> List[str]:
        while self.next_step < len(self.steps):
            step_index = self.next_step
            step = self.steps[step_index]
            try:
                result = execute_step(step)
            except Exception as exc:
                raise WorkflowExecutionError(step_index, exc, self.results) from exc
            self.results.append(result)
            self.next_step += 1
        return list(self.results)


def execute_workflow(steps: List[Any]) -> List[str]:
    """按计划顺序执行整个 workflow。"""
    return WorkflowRunner(steps)()


def enqueue_task_execution(
    steps: List[Any],
    owner_id: str = "default",
    max_retries: int = 0,
    retry_delay: float = 0.0,
    workflow_store: Optional[WorkflowStore] = None,
):
    """把完整 workflow 加入后台队列，并返回单个任务 ID。"""
    if workflow_store is None:
        runner = WorkflowRunner(steps)
    else:
        workflow_id = uuid.uuid4().hex
        workflow_store.create_workflow(
            workflow_id,
            owner_id,
            steps,
            max_retries,
            retry_delay,
        )
        runner = DurableWorkflowRunner(workflow_store, workflow_id)
    task_id = enqueue_task(
        runner,
        owner_id=owner_id,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    return {"status": "queued", "task_id": task_id, "task_ids": [task_id]}
