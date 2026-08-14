"""最小可运行 Agent 示例

提供 `handle_input()` 供测试调用，以及 CLI 主循环用于手工运行。
"""
import asyncio
import json
import os
import sys
import uuid
from functools import partial

if __package__ is None and __name__ == "__main__":
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    if root not in sys.path:
        sys.path.insert(0, root)

from src.agent import config
from src.agent.application.execution.service import (
    enqueue_task_execution,
    execute_plan_items,
    execute_plan_items_detailed,
)
from src.agent.domain.capabilities.models import ToolResult, ToolResultStatus
from src.agent.infrastructure.mcp.adapter import decode_remote_tool_name
from src.agent.infrastructure.memory.memory_manager import initialize_memory, save_memory
from src.agent.application.planning.service import plan_task, planner_visible_specs
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


_STRUCTURED_BLOCK_TYPES = {
    "security.get_event_summary": "security_summary",
    "security.list_events": "security_events",
    "security.get_event_detail": "security_event_detail",
    "security.get_shift_context": "shift_context",
}


def _display_tool_name(tool_name: str) -> str:
    """Decode an MCP remote name without exposing its internal namespace."""
    segment = tool_name.rsplit(".", 1)[-1]
    if not segment.startswith("mcp-encoded-"):
        return tool_name
    try:
        return decode_remote_tool_name(segment)
    except ValueError:
        return tool_name


def _tool_content(content):
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    if isinstance(content, dict) and "data" in content:
        return content["data"]
    return content


def _build_response_blocks(tool_results: list[ToolResult]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for result in tool_results:
        tool_name = _display_tool_name(result.tool)
        if result.status != ToolResultStatus.SUCCESS:
            blocks.append({
                "type": "tool_error",
                "tool": tool_name,
                "data": {"error_code": result.error_code, "retryable": result.retryable},
            })
            continue
        blocks.append({
            "type": _STRUCTURED_BLOCK_TYPES.get(tool_name, "tool_result"),
            "tool": tool_name,
            "data": _tool_content(result.content),
        })
    return blocks


def _response_message(blocks: list[dict[str, object]], results: list[str]) -> str:
    for block in blocks:
        data = block.get("data")
        block_type = block.get("type")
        if block_type == "security_summary" and isinstance(data, dict):
            risk_counts = data.get("risk_counts")
            if not isinstance(risk_counts, dict):
                risk_counts = {}
            urgent_count = sum(
                value
                for level in ("critical", "high")
                if isinstance(value := risk_counts.get(level, 0), (int, float))
            )
            return f"当前园区有 {data.get('total_events', 0)} 个归并安防事件，其中严重/高风险 {urgent_count} 个。"
        if block_type == "security_events" and isinstance(data, list):
            return f"已找到 {len(data)} 个符合条件的安防事件。"
        if block_type == "security_event_detail" and isinstance(data, dict):
            return f"已获取事件 {data.get('event_id', 'unknown')} 的证据链和处置信息。"
        if block_type == "shift_context" and isinstance(data, dict):
            return "当前已获取值班覆盖和升级通知规则。"
        if block_type == "tool_error":
            return "Agent 调用安防能力失败，请检查服务状态或权限。"
    return "; ".join(results)


async def handle_input_async(
    prompt: str,
    user_id: str = "default",
    skill_catalog: SkillCatalog | None = None,
) -> str:
    """对外接口：接收输入，规划并执行，返回合并后的结果字符串。"""
    registry = get_capability_registry()
    active_skill_ids = _resolve_active_skill_ids(prompt, skill_catalog)
    structured_mode = _structured_tool_calling_enabled()
    visible_specs = planner_visible_specs(registry.list_specs())
    steps = await asyncio.to_thread(
        partial(
            plan_task,
            prompt,
            user_id=user_id,
            tool_specs=visible_specs,
            structured_tools=structured_mode,
        )
    )
    run_id = uuid.uuid4().hex
    execution_kwargs = {
        "owner_id": user_id,
        "run_id": run_id,
        "active_skill_ids": active_skill_ids,
        "registry": registry,
    }
    if structured_mode:
        execution_kwargs["allowed_tools"] = {spec.name for spec in visible_specs}
    results = await execute_plan_items(steps, **execution_kwargs)
    separator = "; " if structured_mode else " | "
    return separator.join(results)


async def handle_input_structured_async(
    prompt: str,
    user_id: str = "default",
    skill_catalog: SkillCatalog | None = None,
) -> dict[str, object]:
    """Return a UI-safe message plus typed blocks while preserving the text API."""
    registry = get_capability_registry()
    active_skill_ids = _resolve_active_skill_ids(prompt, skill_catalog)
    structured_mode = _structured_tool_calling_enabled()
    visible_specs = planner_visible_specs(registry.list_specs())
    steps = await asyncio.to_thread(
        partial(
            plan_task,
            prompt,
            user_id=user_id,
            tool_specs=visible_specs,
            structured_tools=structured_mode,
        )
    )
    run_id = uuid.uuid4().hex
    execution_kwargs = {
        "owner_id": user_id,
        "run_id": run_id,
        "active_skill_ids": active_skill_ids,
        "registry": registry,
    }
    if structured_mode:
        execution_kwargs["allowed_tools"] = {spec.name for spec in visible_specs}
    report = await execute_plan_items_detailed(steps, **execution_kwargs)
    blocks = _build_response_blocks(report.tool_results)
    return {
        "message": _response_message(blocks, report.results),
        "blocks": blocks,
        "run_id": run_id,
    }


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
