# Task 4 Report: Verify fake MCP discovery and end-to-end API invocation

## Status

DONE

## Files changed

- Modified: `src/agent/main.py`
- Modified: `src/agent/planner.py`
- Modified: `tests/fixtures/mcp_echo_server.py`
- Modified: `tests/test_mcp_manager.py`
- Modified: `tests/test_plugin_api.py`
- Added: `tests/test_structured_tool_runtime.py`

## RED evidence

Command:

```powershell
python -m pytest tests/test_structured_tool_runtime.py tests/test_plugin_api.py tests/test_mcp_manager.py -q
```

Observed before fix:

- `tests/test_structured_tool_runtime.py` failed because structured `tool_call` dicts fell through to `execute_step()` and then `_invoke_tool()` / `get_tool()` instead of `CapabilityRegistry.invoke()`.
- Exact failure path:
  - `src/agent/main.py:handle_input_async()`
  - `src/agent/executor.py:execute_plan_items()`
  - `src/agent/executor.py:execute_step()`
  - `src/agent/executor.py:_invoke_tool()`
- Exact visible symptom:

```text
ValueError: Unknown tool: demo.local.park_energy
```

Root cause:

- `src/agent/main.py` imported `STRUCTURED_TOOL_CALLING_ENABLED` as an import-time constant, so the runtime used the stale default `False` instead of the test-configured runtime flag.
- With structured mode effectively off, fake LLM `tool_call` objects were not normalized into `ToolCallPlan`, so they never reached the capability registry path.

## GREEN evidence

Focused command:

```powershell
python -m pytest tests/test_structured_tool_runtime.py tests/test_plugin_api.py tests/test_mcp_manager.py -q
```

Result:

```text
36 passed in 14.01s
```

## Full-suite result

Command:

```powershell
python -m pytest -q
```

Result:

```text
310 passed, 1 skipped, 1 warning in 19.94s
```

Warning retained:

- Existing upstream dependency warning from `google.genai.types` during `tests/test_embeddings_gemini.py`; unrelated to Task 4.

## Lifecycle and security coverage

- Verified real `lifespan` startup discovers and registers the allowlisted stdio MCP tool through:
  - `PluginLoader`
  - `MCPClientManager.start_catalog()`
  - `prepare_server_tools()`
  - `CapabilityRegistry`
- Verified direct `handle_input_async()` structured execution under real app lifespan using `server.app.router.lifespan_context(server.app)` to keep MCP client usage on the same event loop as startup/cleanup.
- Verified `/api/handle` end-to-end invocation through the actual FastAPI route and observed `CapabilityRegistry.invoke()` being called for `demo.local.park_energy`.
- Verified shutdown unregisters the fake MCP tool and a second lifespan does not duplicate registration.
- Verified a real stdio MCP client can start against the fixture and list only the fixture tools.
- Verified negative structured cases:
  - unallowlisted namespaced tool returns `unknown_tool`
  - schema-invalid arguments return `invalid_tool_arguments`
- Kept stdio security intact:
  - tests still use `validate_stdio_config()`
  - tests still require exact `sys.executable` allowlisting
  - no allowlist bypasses
  - no network calls

## Implementation notes

- Extended the existing MCP echo fixture with deterministic `park_energy` structured JSON output.
- Added a minimal runtime fix in `src/agent/main.py` and `src/agent/planner.py` so structured-tool mode is read at runtime from `src.agent.config`, while preserving existing module-level monkeypatch compatibility for older tests.
- Did not modify production MCP transport, MCP security validation logic, Compose, README, or architecture docs.

## Self-review

- Confirmed scope stayed within Task 4.
- Confirmed no production MCP transport or security semantics were weakened.
- Confirmed new tests exercise the real registration/invocation path instead of bypassing `PluginLoader`, `MCPClientManager`, or `lifespan`.
- Confirmed the direct lifespan test avoids the unsafe cross-event-loop pattern that caused stdio timeouts when mixing `TestClient` background lifespan with same-test direct async MCP calls.

## Concerns

- The runtime flag compatibility layer in `src/agent/main.py` and `src/agent/planner.py` is intentionally small, but it does introduce a module-level override hook for backwards-compatible monkeypatching. It is covered by the existing suite, but future cleanup could remove that shim once tests stop patching module constants directly.
- The full suite still emits one unrelated external dependency deprecation warning.
