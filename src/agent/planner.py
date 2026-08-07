from pathlib import Path
from typing import List, Optional

from src.agent.config import ENABLE_MEMORY, VECTOR_MEMORY_PATH
from src.agent.llm import LLMAdapter
from src.agent.llm_factory import create_llm_adapter
from src.agent.memory import get_global_memory
from src.agent.memory_manager import add_memory, get_relevant_memory, initialize_memory


def plan_task(prompt: str, user_id: str = "default", llm: Optional[LLMAdapter] = None) -> List[str]:
    """将输入转换为待执行步骤；支持注入 LLMAdapter（若为空则使用默认行为）。"""
    if ENABLE_MEMORY:
        initialize_memory()

    mem = get_global_memory()
    mem.add(user_id, {"prompt": prompt})

    if ENABLE_MEMORY:
        relevant = get_relevant_memory(prompt, top_k=2)
        if relevant:
            prompt = "\n".join([f"Memory: {item['text']}" for item in relevant]) + "\n\n" + prompt

    add_memory(prompt, {"user_id": user_id})

    if llm is None:
        llm = create_llm_adapter()

    return llm.plan(prompt)


def build_plan_summary(steps: List[str]) -> str:
    return "; ".join(steps)
