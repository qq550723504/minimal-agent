import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Collection, List, Optional

from src.agent.config import MAX_TOOL_RESULT_BYTES
from src.agent.domain.planning.models import PlanItem, ToolCallPlan
from src.agent.infrastructure.workflows.task_queue import enqueue_task, get_workflow_queue, get_workflow_store
from src.agent.tool_registry import get_capability_registry, get_tool
from src.agent.infrastructure.workflows.workflow_store import WorkflowStore
from src.agent.domain.capabilities.models import (
    ToolCall,
    ToolInvocationContext,
    ToolResult,
    ToolResultStatus,
)
from src.agent.domain.capabilities.registry import CapabilityRegistry

# 导入默认工具注册模块
import src.agent.tools  # noqa: F401


class WorkflowExecutionError(RuntimeError):
    def __init__(self, step_index: int, cause: Exception, completed_results=None):
        self.step_index = step_index
        self.cause = cause
        self.completed_results = list(completed_results or [])
        super().__init__(f"workflow step {step_index} failed: {cause}")


@dataclass(frozen=True)
class ExecutionReport:
    """Rendered step results plus structured tool outcomes for API consumers."""

    results: list[str]
    tool_results: list[ToolResult]


def _invoke_tool(tool_name: str, payload: str) -> str:
    tool = get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    return tool(payload)


def execute_tool_step(step: str) -> str:
    """执行通用工具步骤。"""
    if not step:
        raise ValueError("tool step is empty")

    parts = step.split(" ", 1)
    tool_name = parts[0].strip().lower().rstrip(":")
    payload = parts[1].strip() if len(parts) > 1 else ""
    return _invoke_tool(tool_name, payload)


def execute_step(step: Any) -> str:
    """执行单条步骤。"""
    if isinstance(step, dict):
        tool_name = step.get("tool")
        if isinstance(tool_name, str):
            payload = step.get("payload", "")
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            return _invoke_tool(tool_name, payload)

        action = step.get("action") or step.get("text") or step.get("step")
        if isinstance(action, str):
            return execute_step(action)
        return json.dumps(step, ensure_ascii=False)

    if not isinstance(step, str):
        return json.dumps(step, ensure_ascii=False)

    text = step.strip()
    if text.startswith("echo: "):
        return text.replace("echo: ", "", 1)

    matcher = re.match(r"^(?P<tool>[A-Za-z0-9_]+):?\s*(?P<payload>.*)$", text)
    if matcher:
        tool_name = matcher.group("tool").lower()
        if get_tool(tool_name):
            return execute_tool_step(text)

    return text


def execute_tasks(steps: List[Any]) -> List[str]:
    """同步执行步骤列表。"""
    return [execute_step(step) for step in steps]


async def execute_tool_call(
    call: ToolCall,
    context: ToolInvocationContext,
    registry: CapabilityRegistry | None = None,
) -> ToolResult:
    """Execute one structured tool call through the capability registry."""
    active_registry = registry or get_capability_registry()
    return await active_registry.invoke(call, context)


async def execute_structured_calls(
    calls: List[ToolCall],
    context: ToolInvocationContext,
    registry: CapabilityRegistry | None = None,
) -> List[ToolResult]:
    """Execute structured tool calls sequentially, preserving their order."""
    results = []
    for call in calls:
        results.append(await execute_tool_call(call, context, registry))
    return results


def _bounded_json_dumps(value: Any) -> str:
    return _bounded_json_dumps_with_limit(value, enforce_limit=True)


def _bounded_json_dumps_with_limit(value: Any, *, enforce_limit: bool) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if enforce_limit and len(rendered.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
        raise ValueError("rendered tool result exceeds size limit")
    return rendered


def _tool_result_error_payload(
    *,
    status: str = "error",
    error_code: str | None,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "status": status,
        "error_code": error_code,
        "retryable": retryable,
    }


def _render_tool_result(result: ToolResult) -> str:
    if result.status == "success":
        if isinstance(result.content, str):
            if len(result.content.encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
                return _bounded_json_dumps_with_limit(
                    _tool_result_error_payload(
                        error_code="tool_result_too_large",
                        retryable=False,
                    ),
                    enforce_limit=False,
                )
            return result.content
        try:
            return _bounded_json_dumps(result.content)
        except ValueError:
            return _bounded_json_dumps_with_limit(
                _tool_result_error_payload(
                    error_code="tool_result_too_large",
                    retryable=False,
                ),
                enforce_limit=False,
            )

    return _bounded_json_dumps_with_limit(
        _tool_result_error_payload(
            status=str(result.status),
            error_code=result.error_code,
            retryable=result.retryable,
        ),
        enforce_limit=False,
    )


def _restore_legacy_step(step: str) -> Any:
    stripped = step.strip()
    if not stripped.startswith("{"):
        return step
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return step
    if not isinstance(parsed, dict):
        return step
    if isinstance(parsed.get("tool"), str):
        return parsed
    if any(isinstance(parsed.get(key), str) for key in ("action", "text", "step")):
        return parsed
    return step


async def _execute_plan_items(
    steps: list[PlanItem],
    owner_id: str,
    run_id: str | None = None,
    active_skill_ids: tuple[str, ...] = (),
    registry: CapabilityRegistry | None = None,
    allowed_tools: Collection[str] | None = None,
) -> ExecutionReport:
    """执行文本步骤和结构化工具调用，并阻止 Planner 调用未授权的隐藏工具。"""

    context = ToolInvocationContext(
        owner_id=owner_id,
        run_id=run_id,
        active_skill_ids=active_skill_ids,
    )
    active_registry = registry or get_capability_registry()
    results: list[str] = []
    tool_results: list[ToolResult] = []
    for step in steps:
        if isinstance(step, ToolCallPlan):
            if (
                allowed_tools is not None
                and step.tool not in allowed_tools
                and active_registry.get_spec(step.tool) is not None
            ):
                tool_result = ToolResult(
                    call_id=step.call_id,
                    tool=step.tool,
                    status=ToolResultStatus.ERROR,
                    error_code="tool_not_planner_visible",
                )
            else:
                tool_result = await execute_tool_call(
                    ToolCall(call_id=step.call_id, tool=step.tool, arguments=step.arguments),
                    context,
                    active_registry,
                )
            tool_results.append(tool_result)
            results.append(_render_tool_result(tool_result))
            continue

        legacy_step = _restore_legacy_step(step) if isinstance(step, str) else step
        results.append(await asyncio.to_thread(execute_step, legacy_step))
    return ExecutionReport(results=results, tool_results=tool_results)


async def execute_plan_items(
    steps: list[PlanItem],
    owner_id: str,
    run_id: str | None = None,
    active_skill_ids: tuple[str, ...] = (),
    registry: CapabilityRegistry | None = None,
    allowed_tools: Collection[str] | None = None,
) -> list[str]:
    """Execute plan items and preserve the legacy list-of-strings contract."""

    report = await _execute_plan_items(
        steps,
        owner_id=owner_id,
        run_id=run_id,
        active_skill_ids=active_skill_ids,
        registry=registry,
        allowed_tools=allowed_tools,
    )
    return report.results


async def execute_plan_items_detailed(
    steps: list[PlanItem],
    owner_id: str,
    run_id: str | None = None,
    active_skill_ids: tuple[str, ...] = (),
    registry: CapabilityRegistry | None = None,
    allowed_tools: Collection[str] | None = None,
) -> ExecutionReport:
    """Execute plan items while retaining structured tool metadata."""

    return await _execute_plan_items(
        steps,
        owner_id=owner_id,
        run_id=run_id,
        active_skill_ids=active_skill_ids,
        registry=registry,
        allowed_tools=allowed_tools,
    )


class DurableWorkflowRunner:
    """从 SQLite 状态执行 workflow，并跳过已经完成的步骤。"""

    def __init__(self, store: WorkflowStore, workflow_id: str):
        self.store = store
        self.workflow_id = workflow_id
        self.__name__ = "execute_workflow"

    def __call__(self) -> List[str]:
        record = self.store.get_workflow(self.workflow_id)
        if record is None:
            raise KeyError(f"workflow not found: {self.workflow_id}")
        if record["status"] == "completed":
            return list(record["results"])

        self.store.start_workflow(self.workflow_id)
        results: List[str] = []
        for step_record in record["steps"]:
            step_index = step_record["step_index"]
            if step_record["status"] == "completed":
                results.append(step_record["result"])
                continue

            try:
                self.store.start_step(self.workflow_id, step_index)
                result = execute_step(step_record["definition"])
            except Exception as exc:
                raise WorkflowExecutionError(step_index, exc, results) from exc

            results.append(result)
            self.store.complete_step(self.workflow_id, step_index, result, results)

        self.store.complete_workflow(self.workflow_id, results)
        return list(results)


class WorkflowRunner:
    """执行 workflow，并在队列重试时从失败步骤继续。"""

    def __init__(self, steps: List[Any]):
        self.steps = list(steps)
        self.results: List[str] = []
        self.next_step = 0
        self.__name__ = "execute_workflow"

    def __call__(self) -> List[str]:
        while self.next_step < len(self.steps):
            step_index = self.next_step
            step = self.steps[step_index]
            try:
                result = execute_step(step)
            except Exception as exc:
                raise WorkflowExecutionError(step_index, exc, self.results) from exc
            self.results.append(result)
            self.next_step += 1
        return list(self.results)


def execute_workflow(steps: List[Any]) -> List[str]:
    """按计划顺序执行整个 workflow。"""
    return WorkflowRunner(steps)()


def enqueue_task_execution(
    steps: List[Any],
    owner_id: str = "default",
    max_retries: int = 0,
    retry_delay: float = 0.0,
    workflow_store: Optional[WorkflowStore] = None,
    workflow_queue=None,
):
    """把完整 workflow 加入后台队列，并返回单个任务 ID。"""
    if workflow_store is None:
        workflow_store = get_workflow_store()
    if workflow_store is None:
        runner = WorkflowRunner(steps)
    else:
        workflow_id = uuid.uuid4().hex
        workflow_store.create_workflow(
            workflow_id,
            owner_id,
            steps,
            max_retries,
            retry_delay,
        )
        queue = workflow_queue or get_workflow_queue()
        if queue.workflow_store is not workflow_store:
            raise ValueError("workflow queue must use the supplied workflow store")
        queue.enqueue_workflow(workflow_id)
        return {
            "status": "queued",
            "task_id": workflow_id,
            "task_ids": [workflow_id],
        }

    runner = WorkflowRunner(steps)
    task_id = enqueue_task(
        runner,
        owner_id=owner_id,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    return {"status": "queued", "task_id": task_id, "task_ids": [task_id]}
