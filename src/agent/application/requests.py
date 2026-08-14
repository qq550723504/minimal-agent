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
from src.agent.domain.planning.models import PlanItem, ToolCallPlan
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
    "energy.query_trend": "energy_trend",
    "energy.query_ranking": "energy_ranking",
    "energy.get_peak_value": "energy_peak",
    "energy.compare_period": "energy_compare",
    "energy.get_alarm_summary": "energy_alarm",
}

_TOOL_NAME_ALIASES = {
    # Common single-character typo emitted for the security shift tool.
    "securiy.get_shift_context": "security.get_shift_context",
}


def _registered_tool_name(registry, remote_name: str) -> str | None:
    for spec in registry.list_specs():
        if _display_tool_name(spec.name) == remote_name:
            return spec.name
    return None


def _quick_plan_for_prompt(prompt: str, registry) -> list[PlanItem] | None:
    """Return deterministic plans for the dashboard's seeded demo queries."""
    text = prompt.lower().replace(" ", "")
    remote_name: str | None = None
    arguments: dict[str, object] = {}
    if "event-fire-003" in text:
        remote_name = "security.get_event_detail"
        arguments = {"event_id": "event-fire-003"}
    elif "event-night-001" in text:
        remote_name = "security.get_event_detail"
        arguments = {"event_id": "event-night-001"}
    elif "值班" in text or "升级规则" in text:
        remote_name = "security.get_shift_context"
        arguments = {"park_id": "park-1", "at_time": "2026-08-11T01:00:00Z"}
    elif "安防态势汇总" in text:
        remote_name = "security.get_event_summary"
        arguments = {"park_id": "park-1"}
    elif "能耗排名" in text or "能耗最高" in text:
        remote_name = "energy.query_ranking"
        arguments = {
            "park_id": "park-1",
            "start_time": "2026-08-07T00:00:00Z",
            "end_time": "2026-08-14T23:59:59Z",
        }
    if remote_name is None:
        return None
    tool_name = _registered_tool_name(registry, remote_name)
    if tool_name is None:
        return None
    return [ToolCallPlan(
        kind="tool_call",
        call_id=f"quick-{remote_name.replace('.', '-')}",
        tool=tool_name,
        arguments=arguments,
    )]


def _display_tool_name(tool_name: str) -> str:
    """Decode an MCP remote name without exposing its internal namespace."""
    segment = tool_name.rsplit(".", 1)[-1]
    if not segment.startswith("mcp-encoded-"):
        return tool_name
    try:
        return decode_remote_tool_name(segment)
    except ValueError:
        return tool_name


def _normalise_planner_tool_aliases(
    steps: list[PlanItem],
    registry,
) -> list[PlanItem]:
    """Map known model tool-name typos back to registered MCP capabilities."""
    canonical_specs = {
        _display_tool_name(spec.name): spec.name
        for spec in registry.list_specs()
    }
    normalised: list[PlanItem] = []
    for step in steps:
        if not isinstance(step, ToolCallPlan) or registry.get_spec(step.tool) is not None:
            normalised.append(step)
            continue
        alias = _TOOL_NAME_ALIASES.get(_display_tool_name(step.tool))
        target = canonical_specs.get(alias) if alias else None
        normalised.append(
            step.model_copy(update={"tool": target}) if target else step
        )
    return normalised


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
        if block_type == "energy_trend" and isinstance(data, dict):
            items = data.get("items")
            return f"已获取能耗趋势，共 {len(items)} 个时间点。" if isinstance(items, list) else "已获取能耗趋势数据。"
        if block_type == "energy_ranking" and isinstance(data, dict):
            items = data.get("items")
            return f"已获取能耗排名，共 {len(items)} 个对象。" if isinstance(items, list) else "已获取能耗排名数据。"
        if block_type == "energy_peak" and isinstance(data, dict):
            return f"当前峰值为 {data.get('peak_value', '—')} {data.get('unit', '')}，发生在 {data.get('peak_time', '—')}。"
        if block_type == "energy_compare" and isinstance(data, dict):
            return f"本期能耗 {data.get('current_total', '—')} {data.get('unit', '')}，较对比期变化 {data.get('change_rate', '—')}。"
        if block_type == "energy_alarm" and isinstance(data, dict):
            return f"发现 {data.get('total', 0)} 条能耗异常，其中严重 {data.get('critical', 0)} 条。"
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
    steps = _quick_plan_for_prompt(prompt, registry)
    if steps is None:
        steps = await asyncio.to_thread(
            partial(
                plan_task,
                prompt,
                user_id=user_id,
                tool_specs=visible_specs,
                structured_tools=structured_mode,
            )
        )
    steps = _normalise_planner_tool_aliases(steps, registry)
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
    steps = _quick_plan_for_prompt(prompt, registry)
    if steps is None:
        steps = await asyncio.to_thread(
            partial(
                plan_task,
                prompt,
                user_id=user_id,
                tool_specs=visible_specs,
                structured_tools=structured_mode,
            )
        )
    steps = _normalise_planner_tool_aliases(steps, registry)
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


async def stream_input_structured_async(
    prompt: str,
    user_id: str = "default",
    skill_catalog: SkillCatalog | None = None,
):
    """Yield progress and the final structured response for an SSE client."""
    registry = get_capability_registry()
    active_skill_ids = _resolve_active_skill_ids(prompt, skill_catalog)
    structured_mode = _structured_tool_calling_enabled()
    visible_specs = planner_visible_specs(registry.list_specs())
    yield {"event": "status", "data": {"stage": "planning", "message": "正在规划查询…"}}
    steps = _quick_plan_for_prompt(prompt, registry)
    if steps is None:
        steps = await asyncio.to_thread(
            partial(
                plan_task,
                prompt,
                user_id=user_id,
                tool_specs=visible_specs,
                structured_tools=structured_mode,
            )
        )
    steps = _normalise_planner_tool_aliases(steps, registry)
    run_id = uuid.uuid4().hex
    execution_kwargs = {
        "owner_id": user_id,
        "run_id": run_id,
        "active_skill_ids": active_skill_ids,
        "registry": registry,
    }
    if structured_mode:
        execution_kwargs["allowed_tools"] = {spec.name for spec in visible_specs}
    yield {
        "event": "status",
        "data": {"stage": "executing", "message": "正在查询数据…", "run_id": run_id},
    }
    results: list[str] = []
    tool_results: list[ToolResult] = []
    for step_index, step in enumerate(steps):
        if isinstance(step, ToolCallPlan):
            yield {
                "event": "tool_started",
                "data": {"step": step_index, "tool": _display_tool_name(step.tool)},
            }
        report = await execute_plan_items_detailed([step], **execution_kwargs)
        results.extend(report.results)
        tool_results.extend(report.tool_results)
        if isinstance(step, ToolCallPlan):
            yield {
                "event": "tool_result",
                "data": {"step": step_index, "blocks": _build_response_blocks(report.tool_results)},
            }
    blocks = _build_response_blocks(tool_results)
    yield {
        "event": "result",
        "data": {"message": _response_message(blocks, results), "blocks": blocks, "run_id": run_id},
    }
    yield {"event": "done", "data": {"run_id": run_id}}


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
