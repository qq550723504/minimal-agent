from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from src.agent import server
from src.agent.infrastructure.llm.llm import LLMAdapter
from src.agent.main import handle_input_async
from src.agent.tool_registry import get_capability_registry


MCP_FIXTURE = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"
MCP_TOOL_NAME = "demo.local.park_energy"
EXPECTED_RESULT = {
    "average_kw": 12.5,
    "park_id": "north-campus",
    "peak_kw": 18.0,
    "window_hours": 24,
}


class StaticPlanLLM(LLMAdapter):
    def __init__(self, plan: list[dict[str, object]]) -> None:
        self._plan = plan

    def plan(self, prompt: str):
        return list(self._plan)


def _write_runtime_plugin(root: Path) -> None:
    plugin = root / "demo"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"""api_version: minimal-agent/v1
id: demo
version: 1.0.0
mcp_servers:
  - id: local
    transport: stdio
    command: {sys.executable}
    args: [{MCP_FIXTURE.as_posix()}]
    allowed_tools:
      - name: park_energy
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, plugin_dir: Path) -> None:
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    monkeypatch.setattr(server.config, "CAPABILITY_RUNTIME_ENABLED", True)
    monkeypatch.setattr(server.config, "STRUCTURED_TOOL_CALLING_ENABLED", True)
    monkeypatch.setattr(server.config, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(server.config, "MCP_STDIO_ALLOWED_COMMANDS", frozenset({sys.executable}))


@pytest.mark.anyio
async def test_structured_runtime_discovers_mcp_tool_executes_it_and_cleans_up_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "plugins"
    _write_runtime_plugin(plugin_dir)
    _configure_runtime(monkeypatch, plugin_dir)
    monkeypatch.setattr(
        "src.agent.application.planning.service.create_llm_adapter",
        lambda: StaticPlanLLM(
            [
                {
                    "kind": "tool_call",
                    "call_id": "park-energy-1",
                    "tool": MCP_TOOL_NAME,
                    "arguments": {"park_id": "north-campus"},
                }
            ]
        ),
    )

    registry = get_capability_registry()

    async with server.app.router.lifespan_context(server.app):
        assert [spec.name for spec in registry.list_specs() if spec.name == MCP_TOOL_NAME] == [
            MCP_TOOL_NAME
        ]
        result = await handle_input_async("Read north campus energy", skill_catalog=server.app.state.skill_catalog)
        assert json.loads(result) == EXPECTED_RESULT

    assert registry.get_spec(MCP_TOOL_NAME) is None

    async with server.app.router.lifespan_context(server.app):
        assert [spec.name for spec in registry.list_specs() if spec.name == MCP_TOOL_NAME] == [
            MCP_TOOL_NAME
        ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("plan_item", "expected_error_code"),
    [
        (
            {
                "kind": "tool_call",
                "call_id": "park-energy-missing",
                "tool": "demo.local.not_allowlisted",
                "arguments": {"park_id": "north-campus"},
            },
            "unknown_tool",
        ),
        (
            {
                "kind": "tool_call",
                "call_id": "park-energy-invalid-args",
                "tool": MCP_TOOL_NAME,
                "arguments": {"window_hours": 24},
            },
            "invalid_tool_arguments",
        ),
    ],
)
async def test_structured_runtime_rejects_unallowlisted_and_invalid_mcp_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    plan_item: dict[str, object],
    expected_error_code: str,
) -> None:
    plugin_dir = tmp_path / "plugins"
    _write_runtime_plugin(plugin_dir)
    _configure_runtime(monkeypatch, plugin_dir)
    monkeypatch.setattr(
        "src.agent.application.planning.service.create_llm_adapter",
        lambda: StaticPlanLLM([plan_item]),
    )

    async with server.app.router.lifespan_context(server.app):
        result = await handle_input_async(
            "Attempt a structured MCP tool call",
            skill_catalog=server.app.state.skill_catalog,
        )

    assert json.loads(result) == {
        "status": "error",
        "error_code": expected_error_code,
        "retryable": False,
    }
