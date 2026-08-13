from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.api import app as server
from src.agent.application.requests import handle_input_async
from src.agent.infrastructure.llm.llm import LLMAdapter
from src.agent.infrastructure.mcp.adapter import encode_remote_tool_name
from src.agent.infrastructure.mcp.manager import MCPClientManager
from src.agent.namespaces import capability_namespaced_id
from src.agent.tool_registry import get_capability_registry


class StaticPlanLLM(LLMAdapter):
    def plan(self, prompt: str):
        return [{
            "kind": "tool_call",
            "call_id": "energy-trend-1",
            "tool": capability_namespaced_id(
                "park-energy", "energy", encode_remote_tool_name("energy.query_trend")
            ),
            "arguments": {
                "park_id": "demo",
                "start_time": "2026-08-04T00:00:00Z",
                "end_time": "2026-08-10T23:59:59Z",
            },
        }]


@pytest.mark.anyio
async def test_agent_runtime_discovers_energy_tool_and_executes_structured_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin = plugin_dir / "park_energy"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        """api_version: minimal-agent/v1
id: park-energy
version: 0.1.0
enabled: true
required: true
mcp_servers:
  - id: energy
    transport: streamable_http
    url_env: PARK_ENERGY_MCP_URL
    allowed_tools:
      - name: energy.query_trend
        side_effects: false
        idempotent: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PARK_ENERGY_MCP_URL", "http://127.0.0.1:8100/mcp")
    monkeypatch.setenv("AGENT_ENABLE_MEMORY", "false")
    monkeypatch.setattr(server.config, "CAPABILITY_RUNTIME_ENABLED", True)
    monkeypatch.setattr(server.config, "STRUCTURED_TOOL_CALLING_ENABLED", True)
    monkeypatch.setattr(server.config, "PLUGIN_DIR", str(plugin_dir))
    monkeypatch.setattr(server.config, "MCP_ALLOWED_HOSTS", frozenset({"127.0.0.1"}))
    monkeypatch.setattr(
        "src.agent.application.planning.service.create_llm_adapter",
        lambda: StaticPlanLLM(),
    )

    class FakeResult:
        is_error = False
        structured_content = {"total": 720.0, "quality": {"validMeterCount": 2}}
        content = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self, cursor=None):
            class Tool:
                name = "energy.query_trend"
                description = "Query energy trend"
                input_schema = {
                    "type": "object",
                    "properties": {
                        "park_id": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                    },
                    "required": ["park_id", "start_time", "end_time"],
                }

                def model_dump(self):
                    return {
                        "name": self.name,
                        "description": self.description,
                        "inputSchema": self.input_schema,
                    }

            return type("Tools", (), {"tools": [Tool()], "next_cursor": None})()

        async def call_tool(self, name, arguments):
            assert name == "energy.query_trend"
            assert arguments["start_time"].startswith("2026-08-04")
            return FakeResult()

    class TestManager(MCPClientManager):
        async def _build_transport(self, config, stack):
            return object()

    monkeypatch.setattr(
        server,
        "MCPClientManager",
        lambda: TestManager(client_factory=lambda transport: FakeClient()),
    )

    async with server.app.router.lifespan_context(server.app):
        print([spec.name for spec in get_capability_registry().list_specs()])
        result = await handle_input_async("查询最近 7 天能耗", skill_catalog=server.app.state.skill_catalog)

    assert json.loads(result) == {"total": 720.0, "quality": {"validMeterCount": 2}}
    tool_name = capability_namespaced_id(
        "park-energy", "energy", encode_remote_tool_name("energy.query_trend")
    )
    assert get_capability_registry().get_spec(tool_name) is None
