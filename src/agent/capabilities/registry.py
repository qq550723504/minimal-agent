import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from jsonschema import Draft202012Validator

from src.agent.config import MAX_TOOL_RESULT_BYTES
from src.agent.observability import observe_tool_call

from .errors import ToolExecutionError
from .models import ToolCall, ToolInvocationContext, ToolResult, ToolResultStatus, ToolSpec


CapabilityHandler = Callable[[dict[str, Any], ToolInvocationContext], Any | Awaitable[Any]]


@dataclass(frozen=True)
class _RegistryEntry:
    spec: ToolSpec
    handler: CapabilityHandler
    validator: Draft202012Validator


class CapabilityRegistry:
    def __init__(self, max_result_bytes: int = MAX_TOOL_RESULT_BYTES):
        self._entries: dict[str, _RegistryEntry] = {}
        self._max_result_bytes = max_result_bytes

    def register(
        self,
        spec: ToolSpec,
        handler: CapabilityHandler,
        *,
        replace: bool = False,
    ) -> None:
        Draft202012Validator.check_schema(spec.input_schema)
        if spec.name in self._entries and not replace:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._entries[spec.name] = _RegistryEntry(
            spec=spec,
            handler=handler,
            validator=Draft202012Validator(spec.input_schema),
        )

    def register_many(self, items: Iterable[tuple[ToolSpec, CapabilityHandler]]) -> None:
        pending = list(items)
        for spec, _ in pending:
            Draft202012Validator.check_schema(spec.input_schema)

        names: set[str] = set()
        for spec, _ in pending:
            if spec.name in self._entries or spec.name in names:
                raise ValueError(f"duplicate tool: {spec.name}")
            names.add(spec.name)

        new_entries = {
            spec.name: _RegistryEntry(
                spec=spec,
                handler=handler,
                validator=Draft202012Validator(spec.input_schema),
            )
            for spec, handler in pending
        }
        self._entries.update(new_entries)

    def get_spec(self, name: str) -> ToolSpec | None:
        entry = self._entries.get(name)
        return entry.spec if entry else None

    def unregister(self, name: str) -> bool:
        """Remove a lifecycle-owned capability and report whether it existed."""

        return self._entries.pop(name, None) is not None

    def list_specs(self) -> list[ToolSpec]:
        return [self._entries[name].spec for name in sorted(self._entries)]

    async def invoke(self, call: ToolCall, context: ToolInvocationContext) -> ToolResult:
        entry = self._entries.get(call.tool)
        started = perf_counter()
        if entry is None:
            result = self._error_result(call, "unknown_tool")
        elif not entry.validator.is_valid(call.arguments):
            result = self._error_result(call, "invalid_tool_arguments")
        else:
            try:
                value = entry.handler(call.arguments, context)
                if inspect.isawaitable(value):
                    value = await asyncio.wait_for(value, timeout=entry.spec.timeout_seconds)
                serialized = json.dumps(value, ensure_ascii=False, default=str)
                if len(serialized.encode("utf-8")) > min(
                    entry.spec.result_size_limit, self._max_result_bytes
                ):
                    result = self._error_result(call, "tool_result_too_large")
                else:
                    result = ToolResult(
                        call_id=call.call_id,
                        tool=call.tool,
                        status=ToolResultStatus.SUCCESS,
                        content=value,
                    )
            except asyncio.TimeoutError:
                result = self._error_result(call, "tool_timeout", retryable=True)
            except ToolExecutionError as error:
                status = (
                    ToolResultStatus.UNKNOWN_OUTCOME
                    if error.unknown_outcome
                    else ToolResultStatus.ERROR
                )
                result = ToolResult(
                    call_id=call.call_id,
                    tool=call.tool,
                    status=status,
                    error_code=error.error_code,
                    retryable=error.retryable,
                )
            except Exception:
                result = self._error_result(call, "tool_execution_failed")

        observe_tool_call(entry.spec if entry is not None else None, result, perf_counter() - started)
        return result

    @staticmethod
    def _error_result(
        call: ToolCall,
        error_code: str,
        *,
        retryable: bool = False,
    ) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            tool=call.tool,
            status=ToolResultStatus.ERROR,
            error_code=error_code,
            retryable=retryable,
        )
