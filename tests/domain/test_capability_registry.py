import asyncio
import time

import pytest

from src.agent.domain.capabilities.errors import ToolExecutionError
from src.agent.domain.capabilities.models import ToolCall, ToolInvocationContext, ToolSpec, ToolSource
from src.agent.domain.capabilities.registry import CapabilityRegistry


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
    assert result.retryable is True


@pytest.mark.anyio
async def test_timeout_applies_to_blocking_sync_handler():
    def slow(arguments, context):
        time.sleep(0.05)

    registry = CapabilityRegistry()
    registry.register(make_spec("demo.sync_slow", timeout_seconds=0.001), slow)

    started = time.perf_counter()
    result = await registry.invoke(
        ToolCall(call_id="sync-1", tool="demo.sync_slow"), ToolInvocationContext()
    )

    assert result.error_code == "tool_timeout"
    assert time.perf_counter() - started < 0.04


@pytest.mark.anyio
async def test_remote_schema_refs_are_rejected_without_retrieval():
    called = False

    def handler(arguments, context):
        nonlocal called
        called = True
        return "unexpected"

    registry = CapabilityRegistry()
    registry.register(
        make_spec(
            "demo.remote_schema",
            input_schema={
                "type": "object",
                "properties": {
                    "value": {"$ref": "https://metadata.internal/schema.json"}
                },
            },
        ),
        handler,
    )

    result = await registry.invoke(
        ToolCall(call_id="schema-1", tool="demo.remote_schema", arguments={"value": 1}),
        ToolInvocationContext(),
    )

    assert result.error_code == "invalid_tool_arguments"
    assert called is False


@pytest.mark.anyio
async def test_schema_validation_runs_under_tool_timeout():
    from src.agent.domain.capabilities.registry import _RegistryEntry

    registry = CapabilityRegistry()
    registry.register(make_spec("demo.schema_slow", timeout_seconds=0.001), lambda *_: None)
    entry = registry._entries["demo.schema_slow"]

    def slow_is_valid(arguments):
        time.sleep(0.05)
        return True

    class SlowValidator:
        def is_valid(self, arguments):
            return slow_is_valid(arguments)

    registry._entries["demo.schema_slow"] = _RegistryEntry(
        spec=entry.spec, handler=entry.handler, validator=SlowValidator()
    )
    result = await registry.invoke(
        ToolCall(call_id="schema-timeout", tool="demo.schema_slow"),
        ToolInvocationContext(),
    )

    assert result.error_code == "tool_timeout"
    assert result.status == "error"


@pytest.mark.anyio
async def test_non_json_result_is_rejected():
    registry = CapabilityRegistry()
    registry.register(make_spec("demo.invalid_result"), lambda *_: {"bad"})

    result = await registry.invoke(
        ToolCall(call_id="invalid-result", tool="demo.invalid_result"),
        ToolInvocationContext(),
    )

    assert result.error_code == "tool_result_not_serializable"


@pytest.mark.anyio
async def test_schema_timeout_is_not_unknown_outcome():
    from src.agent.domain.capabilities.registry import _RegistryEntry

    registry = CapabilityRegistry()
    spec = make_spec(
        "demo.unsafe_schema",
        timeout_seconds=0.001,
        side_effects=True,
        idempotent=False,
    )
    registry.register(spec, lambda *_: "not called")
    entry = registry._entries[spec.name]

    class SlowValidator:
        def is_valid(self, arguments):
            time.sleep(0.05)
            return True

    registry._entries[spec.name] = _RegistryEntry(
        spec=entry.spec, handler=entry.handler, validator=SlowValidator()
    )
    result = await registry.invoke(
        ToolCall(call_id="unsafe-schema", tool=spec.name), ToolInvocationContext()
    )

    assert (result.status, result.error_code) == ("error", "tool_timeout")


@pytest.mark.anyio
async def test_non_idempotent_side_effect_timeout_has_unknown_outcome():
    async def slow(arguments, context):
        await asyncio.sleep(0.05)

    registry = CapabilityRegistry()
    registry.register(
        make_spec(
            "demo.unsafe_timeout",
            timeout_seconds=0.05,
            side_effects=True,
            idempotent=False,
        ),
        slow,
    )

    result = await registry.invoke(
        ToolCall(call_id="unsafe-1", tool="demo.unsafe_timeout"),
        ToolInvocationContext(),
    )

    assert (result.status, result.error_code, result.retryable) == (
        "unknown_outcome",
        "tool_timeout",
        False,
    )


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
