"""最小可运行 Agent 示例

提供 `handle_input()` 供测试调用，以及 CLI 主循环用于手工运行。
"""
import os
import sys
from typing import List

if __package__ is None and __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)

from src.agent.planner import plan_task
from src.agent.executor import execute_tasks, enqueue_task_execution


def handle_input(prompt: str) -> str:
    """对外接口：接收输入，规划并执行，返回合并后的结果字符串。"""
    steps = plan_task(prompt)
    results = execute_tasks(steps)
    return " | ".join(results)


def enqueue_input(prompt: str):
    """对外接口：接收输入后将执行任务加入队列。"""
    steps = plan_task(prompt)
    return enqueue_task_execution(steps)


def main_loop():
    print("Minimal Agent starting. 输入 'quit' 退出。")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            break
        if not prompt:
            continue
        if prompt.strip().lower() in ("quit", "exit"):
            break
        out = handle_input(prompt)
        print(out)


if __name__ == "__main__":
    main_loop()
