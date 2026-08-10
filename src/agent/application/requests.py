"""最小可运行 Agent 示例

提供 `handle_input()` 供测试调用，以及 CLI 主循环用于手工运行。
"""
import asyncio
import os
import sys
import uuid
from functools import partial

if __package__ is None and __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)

from src.agent import config
from src.agent.application.execution.service import enqueue_task_execution, execute_plan_items
from src.agent.infrastructure.memory.memory_manager import initialize_memory, save_memory
from src.agent.application.planning.service import plan_task
from src.agent.infrastructure.skills.loader import SkillCatalog
from src.agent.infrastructure.skills.resolver import SkillResolver
from src.agent.tool_registry import get_capability_registry


STRUCTURED_TOOL_CALLING_ENABLED: bool | None = None


def _resolve_active_skill_ids(
    prompt: str,
    skill_catalog: SkillCatalog | None,
) -> tuple[str, ...]:
    if skill_catalog is None:
        return ()
    return tuple(skill.id for skill in SkillResolver(skill_catalog).resolve(prompt, None))


def _structured_tool_calling_enabled() -> bool:
    override = STRUCTURED_TOOL_CALLING_ENABLED
    if isinstance(override, bool):
        return override
    return config.STRUCTURED_TOOL_CALLING_ENABLED


async def handle_input_async(
    prompt: str,
    user_id: str = "default",
    skill_catalog: SkillCatalog | None = None,
) -> str:
    """对外接口：接收输入，规划并执行，返回合并后的结果字符串。"""
    registry = get_capability_registry()
    active_skill_ids = _resolve_active_skill_ids(prompt, skill_catalog)
    structured_mode = _structured_tool_calling_enabled()
    steps = await asyncio.to_thread(
        partial(
            plan_task,
            prompt,
            user_id=user_id,
            tool_specs=registry.list_specs(),
            structured_tools=structured_mode,
        )
    )
    run_id = uuid.uuid4().hex
    results = await execute_plan_items(
        steps,
        owner_id=user_id,
        run_id=run_id,
        active_skill_ids=active_skill_ids,
        registry=registry,
    )
    separator = "; " if structured_mode else " | "
    return separator.join(results)


def handle_input(prompt: str, user_id: str = "default") -> str:
    """Synchronous compatibility wrapper for CLI/tests outside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(handle_input_async(prompt, user_id=user_id))
    raise RuntimeError("handle_input() cannot run inside an active event loop; use handle_input_async().")


def enqueue_input(prompt: str, user_id: str = "default"):
    """对外接口：接收输入后将执行任务加入队列。"""
    steps = plan_task(prompt, user_id=user_id, structured_tools=False)
    return enqueue_task_execution(steps, owner_id=user_id)


def main_loop():
    initialize_memory()
    print("Minimal Agent starting. 输入 'quit' 退出。")
    try:
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
    finally:
        save_memory()


if __name__ == "__main__":
    main_loop()
