from typing import List, Optional

from src.agent.llm import LLMAdapter
from src.agent.llm_factory import create_llm_adapter
from src.agent.memory import get_global_memory
from src.agent.memory_manager import add_memory, get_relevant_memory, initialize_memory, is_memory_enabled


def _format_conversation_history(conversation_history: List[dict]) -> str:
    history_lines = [f"- {item.get('prompt', '')}" for item in conversation_history if item.get("prompt")]
    return "Conversation history:\n" + "\n".join(history_lines) if history_lines else ""


def _format_relevant_memory(memories: List[dict]) -> str:
    memory_lines = [
        f"- {item['text']}" + (
            f" (source={item['metadata'].get('source')})" if item.get('metadata') and item['metadata'].get('source') else ""
        )
        for item in memories
    ]
    return "Relevant memory:\n" + "\n".join(memory_lines) if memory_lines else ""


def _build_rag_prompt(prompt: str, memories: List[dict], conversation_history: Optional[List[dict]] = None) -> str:
    if not memories and not conversation_history:
        return prompt

    sections = []
    if conversation_history:
        history_section = _format_conversation_history(conversation_history)
        if history_section:
            sections.append(history_section)

    if memories:
        memory_section = _format_relevant_memory(memories)
        if memory_section:
            sections.append(memory_section)

    context_block = "\n\n".join(sections)
    return (
        "System:\n"
        "You are an AI planning assistant. Use the provided context to produce an actionable plan. "
        "If the context is not relevant, prioritize the task description.\n\n"
        f"{context_block}\n\n"
        "Task:\n"
        f"{prompt}\n\n"
        "Response format:\n"
        "Provide each step on a separate line without markdown bullets."
    )


def plan_task(prompt: str, user_id: str = "default", llm: Optional[LLMAdapter] = None) -> List[str]:
    """将输入转换为待执行步骤；支持注入 LLMAdapter（若为空则使用默认行为）。"""
    if is_memory_enabled():
        initialize_memory()

    mem = get_global_memory()
    conversation_history: List[dict] = []
    if user_id != "default":
        conversation_history = mem.recent(user_id, limit=5)

    wrapped_prompt = prompt
    relevant: List[dict] = []
    if is_memory_enabled():
        relevant = get_relevant_memory(prompt, top_k=3, user_id=user_id)

    if relevant or conversation_history:
        wrapped_prompt = _build_rag_prompt(prompt, relevant, conversation_history)

    if user_id != "default":
        mem.add(user_id, {"prompt": prompt})

    if is_memory_enabled():
        add_memory(prompt, {"user_id": user_id})

    if llm is None:
        llm = create_llm_adapter()

    return llm.plan(wrapped_prompt)


def build_plan_summary(steps: List[str]) -> str:
    return "; ".join(steps)
