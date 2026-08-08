# Capability Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace text-guessed tool execution with typed, schema-validated, async-capable tool contracts while preserving every legacy tool and workflow behavior.

**Architecture:** Introduce Pydantic capability models and an isolated `CapabilityRegistry`. Existing `tool_registry.py` becomes a compatibility facade that registers string-payload tools into the new registry, while old synchronous Executor entry points remain available.

**Tech Stack:** Python 3.11, Pydantic 2.13.4, jsonschema 4.26.0, pytest 9.1.1, asyncio.

## Global Constraints

- Preserve `register_tool(name, func, description)`, `get_tool`, `execute_step`, and fixed WorkflowStore behavior.
- New executable calls use exact `ToolCall` objects; do not infer MCP arguments from free text.
- Local and future MCP tools share `ToolSpec`, `ToolInvocationContext`, `ToolResult`, and `ToolExecutionError`.
- JSON Schema validation uses `jsonschema==4.26.0`; do not write a partial schema validator.
- Reject duplicate structured tool names; the legacy facade may replace an existing legacy-only registration to preserve current tests.
- No Plugin, Skill, MCP, Agent loop, API, or persistence work belongs in this plan.

---

## File Map

- Create `src/agent/capabilities/__init__.py`: public capability exports.
- Create `src/agent/capabilities/models.py`: Pydantic models and enums.
- Create `src/agent/capabilities/errors.py`: stable tool execution exception.
- Create `src/agent/capabilities/registry.py`: async registry and invocation validation.
- Modify `src/agent/tool_registry.py:1-33`: legacy compatibility facade.
- Modify `src/agent/executor.py:22-72`: structured async execution entry points.
- Modify `src/agent/config.py:4-17`: global tool result size limit.
- Modify `requirements.txt:1-10`: pin jsonschema.
- Create `tests/test_capability_models.py`.
- Create `tests/test_capability_registry.py`.
- Modify `tests/test_executor.py`.

### Task 1: Define capability contracts

**Files:**
- Create: `src/agent/capabilities/__init__.py`
- Create: `src/agent/capabilities/models.py`
- Create: `src/agent/capabilities/errors.py`
- Modify: `requirements.txt:1-10`
- Modify: `src/agent/config.py:4-17`
- Test: `tests/test_capability_models.py`

**Interfaces:**
- Produces: `ToolSpec`, `ToolCall`, `ToolInvocationContext`, `ToolResult`, `ToolResultStatus`, `ToolSource`, `ToolExecutionError`.

- [ ] **Step 1: Write failing model tests**

```python
import pytest
from pydantic import ValidationError

from src.agent.capabilities.models import ToolCall, ToolSpec, ToolSource


def test_tool_spec_requires_retry_semantics():
    with pytest.raises(ValidationError):
        ToolSpec(
            name="demo.read",
            input_schema={"type": "object"},
            source=ToolSource.LOCAL,
        )


def test_tool_call_rejects_non_object_arguments():
    with pytest.raises(ValidationError):
        ToolCall(call_id="call-1", tool="demo.read", arguments=["bad"])
```

- [ ] **Step 2: Run the tests and confirm the missing module failure**

Run: `python -m pytest tests/test_capability_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agent.capabilities'`.

- [ ] **Step 3: Add the pinned dependency and minimal models**

Add `jsonschema==4.26.0` to `requirements.txt` and implement these exact fields:

```python
class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    description: str = ""
    input_schema: dict[str, Any]
    source: ToolSource
    plugin_id: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    side_effects: bool
    idempotent: bool
    result_size_limit: int = Field(default=1_048_576, gt=0)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str = Field(min_length=1, max_length=128)
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationContext(BaseModel):
    owner_id: str = "default"
    run_id: str | None = None
    active_skill_ids: tuple[str, ...] = ()


class ToolResult(BaseModel):
    call_id: str
    tool: str
    status: ToolResultStatus
    content: Any = None
    error_code: str | None = None
    retryable: bool = False
```

`ToolExecutionError` must carry `error_code`, `retryable`, and `unknown_outcome` without embedding secrets in `str(exc)`.

Add `MAX_TOOL_RESULT_BYTES = int(os.getenv("AGENT_MAX_TOOL_RESULT_BYTES", "1048576"))` and reject non-positive values during configuration loading.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_capability_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contracts**

```powershell
git add requirements.txt src/agent/config.py src/agent/capabilities tests/test_capability_models.py
git commit -m "feat: define capability runtime contracts"
```

### Task 2: Build the async capability registry

**Files:**
- Create: `src/agent/capabilities/registry.py`
- Modify: `src/agent/capabilities/__init__.py`
- Test: `tests/test_capability_registry.py`

**Interfaces:**
- Consumes: Task 1 models and `ToolExecutionError`.
- Produces: `CapabilityRegistry.register(spec, handler)`, atomic `register_many(items)`, `get_spec(name)`, `list_specs()`, and `await invoke(call, context)`.

- [ ] **Step 1: Write failing registry tests**

```python
import pytest

from src.agent.capabilities.models import ToolCall, ToolInvocationContext, ToolSpec, ToolSource
from src.agent.capabilities.registry import CapabilityRegistry


@pytest.mark.anyio
async def test_registry_validates_arguments_before_calling_handler():
    called = False

    async def handler(arguments, context):
        nonlocal called
        called = True
        return arguments["count"]

    registry = CapabilityRegistry()
    registry.register(
        ToolSpec(
            name="demo.count",
            input_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
                "additionalProperties": False,
            },
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
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
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_capability_registry.py -q`

Expected: FAIL because `CapabilityRegistry` does not exist.

- [ ] **Step 3: Implement registration and invocation**

Use this handler contract and validate schemas during registration:

```python
CapabilityHandler = Callable[
    [dict[str, Any], ToolInvocationContext],
    Any | Awaitable[Any],
]


class CapabilityRegistry:
    def __init__(self, max_result_bytes: int = MAX_TOOL_RESULT_BYTES):
        self._entries = {}
        self._max_result_bytes = max_result_bytes

    def register(self, spec: ToolSpec, handler: CapabilityHandler, *, replace: bool = False) -> None:
        Draft202012Validator.check_schema(spec.input_schema)
        if spec.name in self._entries and not replace:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._entries[spec.name] = RegistryEntry(
            spec=spec,
            handler=handler,
            validator=Draft202012Validator(spec.input_schema),
        )

    def get_spec(self, name: str) -> ToolSpec | None:
        entry = self._entries.get(name)
        return entry.spec if entry else None

    def list_specs(self) -> list[ToolSpec]:
        return [self._entries[name].spec for name in sorted(self._entries)]

    async def invoke(
        self,
        call: ToolCall,
        context: ToolInvocationContext,
    ) -> ToolResult:
        return await self._invoke_validated(call, context)
```

`RegistryEntry` is a private frozen dataclass containing `spec`, `handler`, and `validator`. Use the compiled validator at invocation. Await handlers only when `inspect.isawaitable(value)` is true. Serialize content with `json.dumps(value, ensure_ascii=False, default=str)` solely to enforce `min(spec.result_size_limit, self._max_result_bytes)`; preserve the original JSON-like content in ToolResult.

`register_many(items)` must validate every schema and every existing/in-batch name collision before modifying `_entries`, then perform one dictionary update. Add a test proving a bad second entry leaves neither entry registered.

- [ ] **Step 4: Add duplicate, async, exception, timeout, and size tests**

Add these concrete cases, reusing a local `make_spec(name, **overrides)` test helper:

```python
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
```

Also add named tests `test_unknown_tool`, `test_result_size_limit`, `test_unexpected_exception_is_sanitized`, and `test_unknown_outcome_error`. Assert exact codes `unknown_tool`, `tool_result_too_large`, `tool_execution_failed`, and status `unknown_outcome` respectively.

Run: `python -m pytest tests/test_capability_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the registry**

```powershell
git add src/agent/capabilities tests/test_capability_registry.py
git commit -m "feat: add async capability registry"
```

### Task 3: Bridge legacy tools without changing behavior

**Files:**
- Modify: `src/agent/tool_registry.py:1-33`
- Modify: `tests/test_tool_registry.py`
- Test: `tests/test_capability_registry.py`

**Interfaces:**
- Consumes: global `CAPABILITY_REGISTRY` from Task 2.
- Produces: unchanged legacy functions plus `get_capability_registry()`.

- [ ] **Step 1: Add a failing compatibility test**

```python
@pytest.mark.anyio
async def test_legacy_registration_is_invokable_as_capability():
    register_tool("legacy_upper", lambda payload: payload.upper(), "Uppercase text")
    registry = get_capability_registry()
    result = await registry.invoke(
        ToolCall(
            call_id="call-1",
            tool="legacy_upper",
            arguments={"payload": "hello"},
        ),
        ToolInvocationContext(),
    )
    assert result.content == "HELLO"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_tool_registry.py tests/test_capability_registry.py -q`

Expected: FAIL because legacy registrations are not visible to the capability registry.

- [ ] **Step 3: Register an exact legacy wrapper**

Keep `_TOOL_REGISTRY` for `get_tool()` compatibility, then register this structured facade:

```python
async def legacy_handler(arguments, _context):
    return func(arguments.get("payload", ""))

spec = ToolSpec(
    name=normalized_name,
    description=description.strip(),
    input_schema={
        "type": "object",
        "properties": {"payload": {"type": "string"}},
        "required": ["payload"],
        "additionalProperties": False,
    },
    source=ToolSource.LOCAL,
    side_effects=True,
    idempotent=False,
)
CAPABILITY_REGISTRY.register(spec, legacy_handler, replace=True)
```

Legacy metadata keeps its existing `name` and `description` response shape. Do not expose internal handler objects through the API.

Change `list_tools()` and `list_tool_metadata()` to read the sorted global CapabilityRegistry so future structured and MCP tools appear automatically; keep the legacy metadata response fields exactly `name` and `description` in this plan.

- [ ] **Step 4: Run compatibility tests**

Run: `python -m pytest tests/test_tool_registry.py tests/test_executor.py tests/test_server_tools.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the compatibility bridge**

```powershell
git add src/agent/tool_registry.py tests/test_tool_registry.py tests/test_capability_registry.py
git commit -m "refactor: bridge legacy tools to capability registry"
```

### Task 4: Add structured async execution

**Files:**
- Modify: `src/agent/executor.py:22-72`
- Modify: `tests/test_executor.py`

**Interfaces:**
- Consumes: `CapabilityRegistry.invoke()` and capability models.
- Produces: `async execute_tool_call(call, context, registry=None) -> ToolResult` and `async execute_structured_calls(calls, context, registry=None) -> list[ToolResult]`.

- [ ] **Step 1: Write a failing structured executor test**

```python
@pytest.mark.anyio
async def test_execute_structured_calls_preserves_order():
    calls = [
        ToolCall(call_id="1", tool="test_record_order", arguments={"payload": "first"}),
        ToolCall(call_id="2", tool="test_record_order", arguments={"payload": "second"}),
    ]
    results = await execute_structured_calls(calls, ToolInvocationContext())
    assert [result.content for result in results] == ["first", "second"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_executor.py::test_execute_structured_calls_preserves_order -q`

Expected: FAIL because `execute_structured_calls` is missing.

- [ ] **Step 3: Add minimal async entry points**

```python
async def execute_tool_call(call, context, registry=None):
    active_registry = registry or get_capability_registry()
    return await active_registry.invoke(call, context)


async def execute_structured_calls(calls, context, registry=None):
    results = []
    for call in calls:
        results.append(await execute_tool_call(call, context, registry))
    return results
```

Do not rewrite `execute_step`, `WorkflowRunner`, or `DurableWorkflowRunner` in this task.

- [ ] **Step 4: Run focused and full regression tests**

Run: `python -m pytest tests/test_executor.py tests/test_tool_registry.py tests/test_capability_models.py tests/test_capability_registry.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: all existing and new tests PASS.

- [ ] **Step 5: Commit the foundation**

```powershell
git add src/agent/executor.py tests/test_executor.py
git commit -m "feat: execute structured tool calls asynchronously"
```

## Plan Completion Gate

Run:

```powershell
python -m pip check
python -m pytest -q
git diff --check
```

Expected: dependency check passes, the complete suite passes, and `git diff --check` emits no errors. Do not start the Plugin/Skill plan until this gate is green.
