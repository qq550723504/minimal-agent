from typing import List


def execute_tasks(steps: List[str]) -> List[str]:
    """执行步骤的最小实现；真实项目可并行/外呼。"""
    results = []
    for s in steps:
        if s.startswith("echo: "):
            results.append(s.replace("echo: ", ""))
        else:
            # 未知步骤返回原始文本
            results.append(s)
    return results
