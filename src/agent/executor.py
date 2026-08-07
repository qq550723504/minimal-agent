from typing import List

from src.agent.task_queue import enqueue_task


def execute_step(step: str) -> str:
    """执行单条步骤。"""
    if step.startswith("echo: "):
        return step.replace("echo: ", "")
    return step


def execute_tasks(steps: List[str]) -> List[str]:
    """同步执行步骤列表。"""
    return [execute_step(step) for step in steps]


def enqueue_task_execution(steps: List[str]) -> str:
    """把步骤加入后台队列执行。"""
    for step in steps:
        enqueue_task(execute_step, step)
    return "queued"
