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


def enqueue_task_execution(steps: List[str], max_retries: int = 0, retry_delay: float = 0.0):
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
