import asyncio

import pytest

from src.agent.capabilities.errors import ToolExecutionError
from src.agent.capabilities.models import ToolCall, ToolInvocationContext, ToolSpec, ToolSource
from src.agent.capabilities.registry import CapabilityRegistry


def make_spec(name: str, **overrides) -> ToolSpec:
    values = {
        "name": name,
        "input_schema": {"type": "object"},
        "source": ToolSource.LOCAL,
        "side_effects": False,
        "idempotent": True,
    }
    values.update(overrides)
    return ToolSpec(**values)


@pytest.mark.anyio
async def test_registry_validates_arguments_before_calling_handler():
    called = False

    async def handler(arguments, context):
        nonlocal called
        called = True
        return arguments["count"]

    registry = CapabilityRegistry()
    registry.register(
        make_spec(
            "demo.count",
            input_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
        ),
        handler,
    )

    result = await registry.invoke(
        ToolCall(call_id="call-1", tool="demo.count", arguments={"count": "bad"}),
        ToolInvocationContext(),
    )

    assert result.status == "error"
    assert result.error_code == "invalid_tool_arguments"
    assert called is False


def test_register_many_is_atomic():
    registry = CapabilityRegistry()

    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register_many([
            (make_spec("demo.same"), lambda arguments, context: "one"),
            (make_spec("demo.same"), lambda arguments, context: "two"),
        ])

    assert registry.list_specs() == []


@pytest.mark.anyio
async def test_timeout_has_stable_error_code():
    async def slow(arguments, context):
        await asyncio.sleep(0.05)

    registry = CapabilityRegistry()
    registry.register(make_spec("demo.slow", timeout_seconds=0.001), slow)

    result = await registry.invoke(ToolCall(call_id="1", tool="demo.slow"), ToolInvocationContext())

    assert (result.status, result.error_code) == ("error", "tool_timeout")


@pytest.mark.anyio
async def test_unknown_tool():
    result = await CapabilityRegistry().invoke(
        ToolCall(call_id="call-1", tool="demo.missing"), ToolInvocationContext()
    )

    assert (result.status, result.error_code) == ("error", "unknown_tool")


@pytest.mark.anyio
async def test_result_size_limit():
    registry = CapabilityRegistry()
    registry.register(make_spec("demo.large", result_size_limit=3), lambda arguments, context: "four")

    result = await registry.invoke(ToolCall(call_id="call-1", tool="demo.large"), ToolInvocationContext())

    assert (result.status, result.error_code) == ("error", "tool_result_too_large")


@pytest.mark.anyio
async def test_unexpected_exception_is_sanitized():
    def handler(arguments, context):
        raise RuntimeError("Authorization: Bearer secret-token")

    registry = CapabilityRegistry()
    registry.register(make_spec("demo.error"), handler)

    result = await registry.invoke(ToolCall(call_id="call-1", tool="demo.error"), ToolInvocationContext())

    assert (result.status, result.error_code, result.content) == (
        "error",
        "tool_execution_failed",
        None,
    )


@pytest.mark.anyio
async def test_unknown_outcome_error():
    def handler(arguments, context):
        raise ToolExecutionError("remote_state_unknown", unknown_outcome=True)

    registry = CapabilityRegistry()
    registry.register(make_spec("demo.unknown"), handler)

    result = await registry.invoke(ToolCall(call_id="call-1", tool="demo.unknown"), ToolInvocationContext())

    assert result.status == "unknown_outcome"
    assert result.error_code == "remote_state_unknown"
