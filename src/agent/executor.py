import json
import re
from typing import Any, List

from src.agent.task_queue import enqueue_task
from src.agent.tool_registry import get_tool

# 导入默认工具注册模块
import src.agent.tools  # noqa: F401


class WorkflowExecutionError(RuntimeError):
    def __init__(self, step_index: int, cause: Exception):
        self.step_index = step_index
        self.cause = cause
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


def execute_workflow(steps: List[Any]) -> List[str]:
    """按计划顺序执行整个 workflow。"""
    results = []
    for step_index, step in enumerate(steps):
        try:
            results.append(execute_step(step))
        except Exception as exc:
            raise WorkflowExecutionError(step_index, exc) from exc
    return results


def enqueue_task_execution(
    steps: List[Any],
    owner_id: str = "default",
    max_retries: int = 0,
    retry_delay: float = 0.0,
):
    """把完整 workflow 加入后台队列，并返回单个任务 ID。"""
    task_id = enqueue_task(
        execute_workflow,
        steps,
        owner_id=owner_id,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    return {"status": "queued", "task_id": task_id, "task_ids": [task_id]}
