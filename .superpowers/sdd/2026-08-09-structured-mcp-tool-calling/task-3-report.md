# Task 3 Report

## Implementation summary
- Added `execute_plan_items(...)` in `src/agent/executor.py` to run mixed text steps and `ToolCallPlan` items sequentially on the current event loop, using `asyncio.to_thread(execute_step, ...)` for legacy synchronous text/tool steps and `CapabilityRegistry.invoke(...)` for structured tool calls.
- Added bounded/stable structured-tool result rendering: successful non-string tool outputs are JSON-encoded, while non-success outcomes are returned as safe JSON objects containing only `status`, `error_code`, and `retryable`.
- Added `handle_input_async(...)` in `src/agent/main.py` to offload synchronous planning with `asyncio.to_thread(...)`, inject the current capability catalog plus `STRUCTURED_TOOL_CALLING_ENABLED`, generate a `uuid.uuid4().hex` run ID, and execute mixed plan items asynchronously.
- Kept `handle_input(...)` as a synchronous compatibility wrapper for CLI/tests, using `asyncio.run(...)` only when no event loop is active and raising a clear runtime error if called from an active loop.
- Updated `src/agent/server.py` so only `/api/handle` becomes `async def` and awaits `handle_input_async(...)`, preserving existing sanitization and audit logging.
- Preserved the legacy queued workflow path by forcing `enqueue_input(...)` to plan with `structured_tools=False`, so the existing synchronous queue runner does not receive `ToolCallPlan` items it cannot execute.

## Files changed
- `src/agent/executor.py`
- `src/agent/main.py`
- `src/agent/server.py`
- `tests/test_executor.py`
- `tests/test_server.py`

## RED/GREEN evidence
- RED: `python -m pytest tests/test_executor.py tests/test_server.py -q` failed during collection with `ImportError: cannot import name 'execute_plan_items' from 'src.agent.executor'`.
- GREEN: after implementation, `python -m pytest tests/test_executor.py tests/test_server.py -q` passed with `26 passed in 1.37s`.

## Full-suite result
- `python -m pytest -q` -> `302 passed, 1 skipped, 1 warning in 13.82s` (warning: existing `google.genai.types` deprecation from `tests/test_embeddings_gemini.py`).

## Self-review
- Verified the FastAPI request path no longer nests `asyncio.run(...)` inside the application event loop.
- Verified structured tool calls now use the lifespan-owned capability registry from the active loop, while legacy text-step execution remains synchronous behind `asyncio.to_thread(...)`.
- Verified the queue entry point remains on the legacy text-step path so enabling structured tool calling does not silently break queued workflows.
- Verified focused coverage now asserts mixed execution order and stable rendering for `unknown_tool`, invalid arguments, `unknown_outcome`, and oversized tool results.

## Concerns
- Queued `/api/handle/queue` execution intentionally remains legacy-only for now; supporting structured tool calls there would require a separate async-capable workflow runner rather than a small patch in Task 3.

## Review fix follow-up (2026-08-09)

### Findings addressed
- High: preserved trigger-matched active Skill IDs on the HTTP async path by resolving them with `SkillResolver` from the app lifecycle `skill_catalog` and forwarding them through `handle_input_async(...) -> execute_plan_items(...) -> ToolInvocationContext`.
- Medium: made executor rendering stable when success content exceeds the global output bound, returning a bounded status object instead of raising, and enforcing the bound for both string and non-string success content.

### Files changed
- `src/agent/executor.py`
- `src/agent/main.py`
- `src/agent/server.py`
- `tests/test_executor.py`
- `tests/test_server.py`

### RED evidence for the review findings

Command:

```powershell
python -m pytest tests/test_executor.py -k rendered_success_exceeds_global_limit -q
```

Output:

```text
FF                                                                       [100%]
================================== FAILURES ===================================
_ test_execute_plan_items_returns_stable_error_when_rendered_success_exceeds_global_limit[asyncio-string] _
E           json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

_ test_execute_plan_items_returns_stable_error_when_rendered_success_exceeds_global_limit[asyncio-object] _
E           ValueError: rendered tool result exceeds size limit

=========================== short test summary info ===========================
FAILED tests/test_executor.py::test_execute_plan_items_returns_stable_error_when_rendered_success_exceeds_global_limit[asyncio-string]
FAILED tests/test_executor.py::test_execute_plan_items_returns_stable_error_when_rendered_success_exceeds_global_limit[asyncio-object]
2 failed, 14 deselected in 0.56s
```

Command:

```powershell
python -m pytest tests/test_server.py -k preserves_active_skill_ids -q
```

Output:

```text
F                                                                        [100%]
================================== FAILURES ===================================
____ test_handle_endpoint_preserves_active_skill_ids_for_async_tool_calls _____
E       AssertionError: assert () == ('demo.review',)

=========================== short test summary info ===========================
FAILED tests/test_server.py::test_handle_endpoint_preserves_active_skill_ids_for_async_tool_calls
1 failed, 12 deselected in 1.12s
```

### GREEN evidence after the fix

Command:

```powershell
python -m pytest tests/test_executor.py -k rendered_success_exceeds_global_limit -q
```

Output:

```text
..                                                                       [100%]
2 passed, 14 deselected in 0.43s
```

Command:

```powershell
python -m pytest tests/test_server.py -k preserves_active_skill_ids -q
```

Output:

```text
.                                                                        [100%]
1 passed, 12 deselected in 1.18s
```

Command:

```powershell
python -m pytest tests/test_executor.py tests/test_server.py -q
```

Output:

```text
.............................                                            [100%]
29 passed in 1.32s
```

Command:

```powershell
python -m pytest -q
```

Output:

```text
........................................................................ [ 23%]
........................................................................ [ 47%]
........................................................................ [ 70%]
...............................................................s........ [ 94%]
..................                                                       [100%]
============================== warnings summary ===============================
tests/test_embeddings_gemini.py::test_gemini_embedding_adapter_uses_embed_content_contract
  C:\Users\Henry\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\google\genai\types.py:42: DeprecationWarning: '_UnionGenericAlias' is deprecated and slated for removal in Python 3.17
    VersionedUnionType = Union[builtin_types.UnionType, _UnionGenericAlias]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
305 passed, 1 skipped, 1 warning in 13.97s
```

### Implementation notes
- `handle_input_async(...)` now accepts an optional `skill_catalog`, resolves trigger-matched Skills once per request, and forwards their IDs with the generated `run_id` and existing `owner_id`.
- `/api/handle` now passes `app.state.skill_catalog` into `handle_input_async(...)`, keeping the change inside the HTTP async path.
- `_render_tool_result(...)` now converts oversized rendered success content into the same stable bounded error payload used for tool execution failures instead of throwing from executor rendering.
