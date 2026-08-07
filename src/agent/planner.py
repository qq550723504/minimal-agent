from typing import List, Optional
from src.agent.memory import get_global_memory
from src.agent.llm import LLMAdapter, MockLLM


def plan_task(prompt: str, user_id: str = "default", llm: Optional[LLMAdapter] = None) -> List[str]:
    """将输入转换为待执行步骤；支持注入 LLMAdapter（若为空则使用默认行为）。"""
    mem = get_global_memory()
    mem.add(user_id, {"prompt": prompt})

    if llm is None:
        # 兼容旧行为：直接封装为一个 echo 步骤
        return [f"echo: {prompt}"]

    # 使用 LLM 生成多步计划
    return llm.plan(prompt)


def build_plan_summary(steps: List[str]) -> str:
    return "; ".join(steps)
