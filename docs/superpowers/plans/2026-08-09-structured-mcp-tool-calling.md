# Structured MCP Tool Calling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect structured model-generated tool calls to the existing CapabilityRegistry so `/api/handle` can safely execute local and MCP tools, while preserving legacy text-step behavior.

**Architecture:** Add a validated platform-neutral plan item for tool calls, inject a safe deterministic capability catalog into the planner prompt, and execute structured calls through the existing asynchronous `CapabilityRegistry.invoke()` path. Keep the synchronous legacy CLI and text-step executor as compatibility wrappers; do not refactor the SQLite worker queue in this slice.

**Tech Stack:** Python 3.11 runtime, FastAPI, Pydantic 2, asyncio, existing `CapabilityRegistry`, MCP SDK 2, pytest, Docker Compose.

## Global Constraints

- Do not implement energy data collection, time-series storage, energy metrics, billing, carbon accounting, or device control.
- Do not rewrite the existing MCP transports or security validation.
- Do not convert the SQLite workflow queue into an MCP-specific asynchronous queue; the first slice supports structured MCP calls on the HTTP request path and preserves existing queue behavior.
- Do not require provider-native function calling; use one JSON planning contract compatible with Mock, OpenAI, and Gemini.
- Keep Mock, `echo`, `http_get`, `http_post`, and legacy string-step behavior working.
- Structured tool calling is controlled by `AGENT_STRUCTURED_TOOL_CALLING_ENABLED` and defaults to `false`.
- Only inject `name`, `description`, `input_schema`, `side_effects`, and `idempotent` into planner prompts; never inject MCP URLs, commands, environment variables, credentials, or Skill contents.
- Every structured call must pass through `CapabilityRegistry.invoke()` and retain stable status, error code, retryability, timeout, and result-size semantics.
- Preserve user ownership and pass `owner_id`, `run_id`, and active Skill IDs into `ToolInvocationContext`.
- Do not claim real provider or real energy-system coverage from fake-client and fake-MCP tests.

---

## File Map

| File | Responsibility in this plan |
| --- | --- |
| `src/agent/plan_models.py` | Validated structured plan-item model and plan-item type alias. |
| `src/agent/config.py` | Feature flag for structured tool calling. |
| `src/agent/llm.py` | Parse and normalize JSON plan items without breaking the existing parser contract. |
| `src/agent/planner.py` | Build deterministic safe tool-catalog prompt and select structured planning mode. |
| `src/agent/executor.py` | Execute mixed text and structured tool steps through legacy or CapabilityRegistry paths. |
| `src/agent/main.py` | Provide async request orchestration and a synchronous compatibility wrapper. |
| `src/agent/server.py` | Use the async orchestration path for `/api/handle`. |
| `tests/test_plan_models.py` | Plan-item validation and parser normalization tests. |
| `tests/test_planner.py` | Tool-catalog prompt and feature-flag behavior tests. |
| `tests/test_executor.py` | Mixed execution, context propagation, and ToolResult rendering tests. |
| `tests/test_server.py` | API integration and backward-compatibility tests. |
| `tests/test_structured_tool_runtime.py` | Fake MCP discovery and end-to-end structured tool invocation tests. |
| `tests/test_deployment_config.py` | Compose forwarding and feature-flag documentation checks. |
| `docker-compose.yml` | Forward the structured-tool feature flag. |
| `README.md` | Document activation, safe defaults, and first-slice limitations. |
| `docs/ARCHITECTURE.md` | Document the structured execution boundary. |

---

### Task 1: Add the validated structured plan-item contract

**Files:**
- Create: `src/agent/plan_models.py`
- Modify: `src/agent/config.py`
- Modify: `src/agent/llm.py`
- Create: `tests/test_plan_models.py`
- Modify: `tests/test_llm.py`

**Interfaces:**
- Produces `ToolCallPlan`, with fields `kind: Literal["tool_call"]`, `call_id: str`, `tool: str`, and `arguments: dict[str, Any]`.
- Produces `PlanItem = str | ToolCallPlan`.
- Produces `parse_structured_plan_output(text: str) -> list[PlanItem]`.
- Produces `normalize_plan_items(items: Sequence[Any]) -> list[PlanItem]` for provider adapters that already parsed JSON into Python values.
- Produces `STRUCTURED_TOOL_CALLING_ENABLED: bool` from `AGENT_STRUCTURED_TOOL_CALLING_ENABLED`, defaulting to `false`.
- Preserves `parse_plan_output(text)` and its existing `list[str | dict]` behavior for existing callers.

- [ ] **Step 1: Write failing model and parser tests**

Add tests covering valid tool calls, extra-field rejection, non-object arguments, empty call IDs, invalid tool names, JSON arrays containing text plus tool calls, malformed JSON fallback, and normalization of the `dict` values returned by the existing provider adapters. The valid case should assert a Pydantic model rather than a raw dictionary:

```python
def test_parse_structured_plan_output_returns_validated_tool_call():
    items = parse_structured_plan_output(
        '[{"kind":"tool_call","call_id":"call-1",'
        '"tool":"energy.query_trend","arguments":{"park_id":"park-a"}}]'
    )

    assert items[0].tool == "energy.query_trend"
    assert items[0].arguments == {"park_id": "park-a"}
```

Add a regression assertion that `parse_plan_output('[{"tool":"legacy","payload":"x"}]')` still returns the original dictionary shape.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_plan_models.py tests/test_llm.py -q
```

Expected: failure because `src/agent/plan_models.py`, the feature flag, and `parse_structured_plan_output` do not yet exist.

- [ ] **Step 3: Implement the minimal contract**

Create the model with `ConfigDict(extra="forbid")`, a lowercase capability-name pattern matching `ToolSpec`, non-empty bounded `call_id`, and `arguments: dict[str, Any]`. Implement `normalize_plan_items` to convert only dictionaries with `kind == "tool_call"` through `ToolCallPlan.model_validate`; preserve strings and return non-tool dictionaries as text-safe serialized items. Implement `parse_structured_plan_output` by reusing `parse_plan_output` and then calling `normalize_plan_items`. If the top-level output cannot be parsed as the structured contract, return text items from the existing fallback instead of executing arbitrary dictionaries.

Add this configuration expression alongside the existing flags:

```python
STRUCTURED_TOOL_CALLING_ENABLED = _bool_env(
    "AGENT_STRUCTURED_TOOL_CALLING_ENABLED", "false"
)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_plan_models.py tests/test_llm.py -q
```

Expected: all focused tests pass, including the pre-existing parser tests.

- [ ] **Step 5: Commit the contract**

```powershell
git add src/agent/plan_models.py src/agent/config.py src/agent/llm.py tests/test_plan_models.py tests/test_llm.py
git commit -m "feat: add structured tool call plan contract"
```

### Task 2: Inject a deterministic safe tool catalog into planning

**Files:**
- Modify: `src/agent/planner.py`
- Modify: `tests/test_planner.py`

**Interfaces:**
- Produces `build_tool_catalog_prompt(specs: Sequence[ToolSpec]) -> str`.
- Extends `plan_task` with optional `tool_specs` and `structured_tools` keyword arguments without changing existing positional arguments.
- When structured mode is disabled, `plan_task` keeps the current prompt and return behavior.

- [ ] **Step 1: Write failing planner tests**

Add tests that assert catalog output is stable by tool name, contains only the five allowed fields, excludes `plugin_id`, URLs, commands, and environment variable names, and asks for the exact JSON array contract. Add a flag-off test proving the injected catalog is absent when `structured_tools=False`.

```python
def test_build_tool_catalog_prompt_is_safe_and_sorted():
    prompt = build_tool_catalog_prompt([spec_b, spec_a])

    assert prompt.index('"name": "a.tool"') < prompt.index('"name": "b.tool"')
    assert "plugin_id" not in prompt
    assert "url_env" not in prompt
    assert '"kind": "tool_call"' in prompt
```

- [ ] **Step 2: Run the focused planner tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_planner.py -q
```

Expected: failure because the catalog builder and structured planner arguments do not exist.

- [ ] **Step 3: Implement catalog injection**

Use `ToolSpec.model_dump`-style selection to construct a stable JSON catalog from the allowed fields. Sort by `spec.name`. Add the catalog and response contract only when structured mode is enabled. Keep memory and conversation-history sections unchanged and place the tool catalog before the task section. After calling the existing synchronous `llm.plan`, call `normalize_plan_items` when structured mode is enabled so the provider adapters' already-parsed dictionaries become validated `ToolCallPlan` instances.

Use the current registry as the default source only when `tool_specs` is not supplied, so unit tests can inject isolated specs without mutating global state:

```python
if tool_specs is None and structured_tools:
    tool_specs = get_capability_registry().list_specs()
```

Keep the existing `plan_task(prompt, user_id, llm)` positional call valid.

- [ ] **Step 4: Run planner and regression tests**

Run:

```powershell
python -m pytest tests/test_planner.py tests/test_llm.py -q
```

Expected: all planner and parser tests pass, with the default mode still producing the old prompt.

- [ ] **Step 5: Commit the planner catalog**

```powershell
git add src/agent/planner.py tests/test_planner.py
git commit -m "feat: expose safe capability catalog to planner"
```

### Task 3: Add mixed asynchronous execution and preserve legacy execution

**Files:**
- Modify: `src/agent/executor.py`
- Modify: `src/agent/main.py`
- Modify: `src/agent/server.py`
- Modify: `tests/test_executor.py`
- Modify: `tests/test_server.py`

**Interfaces:**
- Produces `async execute_plan_items(steps: list[PlanItem], owner_id: str, run_id: str | None = None, active_skill_ids: tuple[str, ...] = (), registry: CapabilityRegistry | None = None) -> list[str]`.
- Produces `async handle_input_async(prompt: str, user_id: str = "default") -> str`.
- Keeps `handle_input(prompt: str, user_id: str = "default") -> str` as a synchronous compatibility wrapper.
- `/api/handle` calls `handle_input_async` from an `async def` route.

- [ ] **Step 1: Write failing executor tests**

Add an async test with one text step and one `ToolCallPlan`. Register a fake capability with a schema requiring `value`, then assert the call executes in order and receives the expected context:

```python
async def test_execute_plan_items_runs_text_and_tool_call_in_order():
    seen = []

    async def handler(arguments, context):
        seen.append((arguments, context.owner_id, context.run_id))
        return {"value": arguments["value"]}

    result = await execute_plan_items(
        ["first", ToolCallPlan(
            kind="tool_call",
            call_id="call-1",
            tool="test.echo",
            arguments={"value": "second"},
        )],
        owner_id="user-1",
        run_id="run-1",
        registry=fake_registry,
    )

    assert result[0] == "first"
    assert '"value": "second"' in result[1]
    assert seen == [({"value": "second"}, "user-1", "run-1")]
```

Add tests for unknown tools, invalid arguments, `unknown_outcome`, and oversized results to assert the stable ToolResult status is rendered rather than raised as an unhandled exception.

- [ ] **Step 2: Run the focused executor and server tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_executor.py tests/test_server.py -q
```

Expected: failure because the mixed async executor and async request entry point do not exist.

- [ ] **Step 3: Implement the async execution bridge**

In `executor.py`, convert each `ToolCallPlan` to the existing `ToolCall` model and call `execute_tool_call` with `ToolInvocationContext`. Execute text steps with `asyncio.to_thread(execute_step, step)` so existing synchronous local tools remain non-blocking to the API event loop. Render successful content as a bounded JSON string for non-string values; render failures as a safe object containing `status`, `error_code`, and `retryable`.

Do not call MCP clients through `asyncio.run` inside the FastAPI request loop. Use the existing lifespan-owned registry and event loop.

In `main.py`, add `handle_input_async` that:

1. calls `plan_task` in `asyncio.to_thread` because current LLM adapters are synchronous;
2. passes the structured-tool feature flag and current capability specs;
3. creates a run ID with `uuid.uuid4().hex`;
4. calls `execute_plan_items`; and
5. returns the existing semicolon-separated summary format.

Keep `handle_input` as a wrapper that uses `asyncio.run` only when called from synchronous CLI or tests. If a running event loop is detected, raise a clear runtime error instructing callers to use `handle_input_async` rather than nesting event loops.

Change only the `/api/handle` route to `async def` and keep audit events and input sanitization in the route.

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_executor.py tests/test_server.py -q
```

Expected: all focused tests pass, including existing synchronous API tests after their test doubles are updated to the async entry point.

- [ ] **Step 5: Commit the execution bridge**

```powershell
git add src/agent/executor.py src/agent/main.py src/agent/server.py tests/test_executor.py tests/test_server.py
git commit -m "feat: execute structured tool calls through capability registry"
```

### Task 4: Verify fake MCP discovery and end-to-end API invocation

**Files:**
- Create: `tests/test_structured_tool_runtime.py`
- Modify: `tests/fixtures/mcp_echo_server.py`
- Modify: `tests/test_plugin_api.py`
- Modify: `tests/test_mcp_manager.py`

**Interfaces:**
- Consumes the plugin manifest and MCP fixture already used by the repository.
- Produces a test-only `park-energy`-shaped MCP tool registration and a `/api/handle` invocation that reaches `CapabilityRegistry.invoke()`.

- [ ] **Step 1: Write the failing integration tests**

Add one test that creates a temporary plugin manifest with a stdio MCP server and an allowed read-only tool. Start the application lifespan with structured calling enabled, assert the tool is present in the registry, inject a fake LLM plan containing a `ToolCallPlan`, call `handle_input_async`, and assert the fake MCP result appears in the response.

Add lifecycle assertions that a second lifespan does not duplicate the tool and shutdown unregisters it. Add a negative test proving a malformed or unallowlisted MCP tool cannot be invoked through the structured plan.

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_structured_tool_runtime.py tests/test_plugin_api.py tests/test_mcp_manager.py -q
```

Expected: failure because the API planner-to-registry bridge is not yet wired to the loaded MCP capability.

- [ ] **Step 3: Implement only the fixture and integration wiring required by the tests**

Extend the existing echo fixture to return deterministic JSON for a declared tool. Keep the test manifest inside the temporary directory and use the exact executable path in the test allowlist so the real stdio security checks remain active. Do not weaken production allowlists or bypass `MCPClientManager`.

Use a fake LLM adapter or monkeypatch at the planner boundary; do not make network calls to OpenAI, Gemini, or a real MCP service.

- [ ] **Step 4: Run the integration tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_structured_tool_runtime.py tests/test_plugin_api.py tests/test_mcp_manager.py -q
```

Expected: fake MCP discovery, invocation, shutdown cleanup, and negative security cases pass.

- [ ] **Step 5: Commit the MCP integration tests**

```powershell
git add tests/test_structured_tool_runtime.py tests/fixtures/mcp_echo_server.py tests/test_plugin_api.py tests/test_mcp_manager.py
git commit -m "test: verify structured MCP tool invocation"
```

### Task 5: Add deployment configuration and operator documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Adds `AGENT_STRUCTURED_TOOL_CALLING_ENABLED` to Compose with a default of `false`.
- Documents the flag, the safe default, the plugin manifest boundary, and the fact that MCP structured calls are supported on `/api/handle` but not yet on the SQLite queue path.

- [ ] **Step 1: Write failing deployment/documentation tests**

Add assertions that Compose forwards the feature flag and README documents all of the following exact points: default disabled, only safe ToolSpec metadata enters the planner prompt, MCP tools are executed through CapabilityRegistry, and queued MCP workflows are outside the first slice.

- [ ] **Step 2: Run the focused deployment tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_deployment_config.py -q
```

Expected: failure because the Compose variable and documentation statements are absent.

- [ ] **Step 3: Implement configuration and documentation**

Add this Compose entry under the `agent.environment` mapping:

```yaml
AGENT_STRUCTURED_TOOL_CALLING_ENABLED: ${AGENT_STRUCTURED_TOOL_CALLING_ENABLED:-false}
```

Document the activation sequence, including `AGENT_CAPABILITY_RUNTIME_ENABLED=true`, MCP host/stdio allowlists, and the requirement that the remote MCP service enforce its own tenant authorization. Update the architecture flow to show `ToolCall -> CapabilityRegistry -> MCP/local handler -> ToolResult`.

- [ ] **Step 4: Run focused deployment checks**

Run:

```powershell
python -m pytest tests/test_deployment_config.py -q
docker compose config --quiet
```

Expected: tests and Compose rendering pass; an unset `OPENAI_API_KEY` may produce the existing Compose warning but must not make rendering fail.

- [ ] **Step 5: Commit deployment documentation**

```powershell
git add docker-compose.yml README.md docs/ARCHITECTURE.md tests/test_deployment_config.py
git commit -m "docs: document structured MCP tool calling configuration"
```

### Task 6: Run the complete verification gate

**Files:**
- Modify only files needed to correct failures found by the verification commands; do not broaden scope.

**Interfaces:**
- Consumes all previous task outputs.
- Produces a clean, tested branch with no uncommitted generated runtime data.

- [ ] **Step 1: Run the complete Python test suite**

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q
```

Expected: the existing baseline remains at least `275 passed, 1 skipped`, plus the new structured-tool tests.

- [ ] **Step 2: Validate dependencies and Compose**

```powershell
python -m pip check
docker compose config --quiet
```

Expected: no broken requirements and successful Compose rendering.

- [ ] **Step 3: Build the runtime image**

```powershell
docker build --tag minimal-agent:structured-mcp .
```

Expected: image build succeeds without copying tests, docs, local data, or secrets into the image.

- [ ] **Step 4: Review the final diff and runtime data**

```powershell
git diff --check
git status --short
git diff --stat HEAD~6..HEAD
```

Confirm only the planned source, test, Compose, and documentation files changed, and no API keys, SQLite files, audit logs, or vector-memory files are staged.

- [ ] **Step 5: Commit any final verification-only correction**

If a correction is required, stage only the planned paths that contain the correction and use a focused message such as:

```powershell
git add src/agent/plan_models.py src/agent/llm.py src/agent/planner.py src/agent/executor.py src/agent/main.py src/agent/server.py tests/test_plan_models.py tests/test_planner.py tests/test_executor.py tests/test_server.py tests/test_structured_tool_runtime.py
git commit -m "fix: address structured MCP verification findings"
```

Do not push or create a PR in this plan; those are separate explicit actions.

## Plan Self-Review

- Spec background and execution-gap diagnosis are covered by Tasks 1-3.
- Safe planner catalog requirements are covered by Task 2.
- Async lifespan ownership and legacy compatibility are covered by Task 3.
- MCP discovery, lifecycle, allowlist, unknown-tool, and fake-server coverage are covered by Task 4.
- Feature flag, Compose, operator documentation, and first-slice queue limitation are covered by Task 5.
- Full verification and no-secret/no-runtime-data checks are covered by Task 6.
- No energy-domain implementation is included; the plan ends with a generic MCP capability that a later energy plugin can consume.
