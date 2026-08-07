import json
import re
from typing import Any, List

from src.agent.task_queue import enqueue_task
from src.agent.tool_registry import get_tool

# 导入默认工具注册模块
import src.agent.tools  # noqa: F401


def execute_tool_step(step: str) -> str:
    """执行通用工具步骤。"""
    try:
        if not step:
            raise ValueError("tool step is empty")

        parts = step.split(" ", 1)
        tool_name = parts[0].strip().lower().rstrip(":")
        payload = parts[1].strip() if len(parts) > 1 else ""

        tool = get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        return tool(payload)
    except Exception as exc:
        return f"ERROR: {exc}"


def execute_step(step: Any) -> str:
    """执行单条步骤。"""
    if isinstance(step, dict):
        tool_name = step.get("tool")
        if isinstance(tool_name, str):
            payload = step.get("payload", "")
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            tool = get_tool(tool_name)
            if tool is None:
                return f"ERROR: Unknown tool: {tool_name}"
            return tool(payload)

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


def enqueue_task_execution(steps: List[Any], max_retries: int = 0, retry_delay: float = 0.0):
    """把步骤加入后台队列执行，并返回任务 ID 列表。"""
    task_ids = []
    for step in steps:
        task_id = enqueue_task(
            execute_step,
            step,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        task_ids.append(task_id)
    return {"status": "queued", "task_ids": task_ids}
