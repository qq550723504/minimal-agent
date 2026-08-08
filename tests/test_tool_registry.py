import pytest

from src.agent.capabilities.models import ToolCall, ToolInvocationContext, ToolSource, ToolSpec
from src.agent.tool_registry import (
    get_capability_registry,
    get_tool,
    list_tool_metadata,
    list_tools,
    register_tool,
)


def test_register_and_get_tool():
    def dummy_tool(payload: str) -> str:
        return payload.upper()

    register_tool("dummy", dummy_tool)
    tool = get_tool("dummy")
    assert tool is dummy_tool
    assert "dummy" in list_tools()


def test_get_unknown_tool():
    assert get_tool("unknown_tool") is None


@pytest.mark.parametrize("name", ["legacy tool", "   "])
def test_invalid_structured_name_keeps_legacy_registration_callable(name):
    expected = name.strip().lower()
    register_tool(name, lambda payload: f"legacy:{payload}", "Legacy-only tool")

    tool = get_tool(name)

    assert tool is not None
    assert tool("hello") == "legacy:hello"
    assert get_capability_registry().get_spec(expected) is None
    assert expected not in list_tools()


@pytest.mark.anyio
async def test_legacy_registration_is_invokable_as_capability():
    register_tool("legacy_upper", lambda payload: payload.upper(), "Uppercase text")

    result = await get_capability_registry().invoke(
        ToolCall(
            call_id="call-1",
            tool="legacy_upper",
            arguments={"payload": "hello"},
        ),
        ToolInvocationContext(),
    )

    assert result.content == "HELLO"


def test_list_tools_includes_sorted_structured_capabilities():
    registry = get_capability_registry()
    registry.register(
        ToolSpec(
            name="structured.catalog",
            description="A structured capability",
            input_schema={"type": "object"},
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
        ),
        lambda arguments, context: "unused",
        replace=True,
    )

    assert list_tools() == sorted(list_tools())
    assert "structured.catalog" in list_tools()
    assert {
        "name": "structured.catalog",
        "description": "A structured capability",
        "source": "local",
        "plugin_id": None,
        "input_schema": {"type": "object"},
        "side_effects": False,
        "idempotent": True,
    } in list_tool_metadata()
