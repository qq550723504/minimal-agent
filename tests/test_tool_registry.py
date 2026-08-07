from src.agent.tool_registry import get_tool, list_tools, register_tool


def test_register_and_get_tool():
    def dummy_tool(payload: str) -> str:
        return payload.upper()

    register_tool("dummy", dummy_tool)
    tool = get_tool("dummy")
    assert tool is dummy_tool
    assert "dummy" in list_tools()


def test_get_unknown_tool():
    assert get_tool("unknown_tool") is None
