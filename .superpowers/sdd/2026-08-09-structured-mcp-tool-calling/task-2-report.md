# Task 2 Report: Inject a deterministic safe tool catalog into planning

## Implementation summary

Implemented Task 2 in planner-only scope.

- Added `build_tool_catalog_prompt(specs: Sequence[ToolSpec]) -> str` in `src/agent/planner.py`.
- Extended `plan_task(...)` with keyword-only `tool_specs` and `structured_tools` arguments while preserving the existing positional call shape `plan_task(prompt, user_id, llm)`.
- Injected the tool catalog and strict JSON-array response contract only when structured mode is enabled.
- Kept the existing memory/conversation-history formatting intact and inserted the tool catalog before the `Task:` section.
- Normalized provider-returned parsed dict items with `normalize_plan_items(...)` only when structured mode is enabled.
- Left executor, main, server, MCP transport, Compose, and later-task behavior untouched.

## Files changed

- Modified: `src/agent/planner.py`
- Modified: `tests/test_planner.py`
- Added: `.superpowers/sdd/2026-08-09-structured-mcp-tool-calling/task-2-report.md`

## TDD

### RED

Command:

```powershell
python -m pytest tests/test_planner.py -q
```

Output:

```text
ERROR tests/test_planner.py
ImportError: cannot import name 'build_tool_catalog_prompt' from 'src.agent.planner'
```

Notes:

- This was the expected Task 2 failure: the catalog builder did not exist yet.

### GREEN

Command:

```powershell
python -m pytest tests/test_planner.py tests/test_llm.py -q
```

Output:

```text
26 passed in 0.39s
```

Notes:

- Added planner tests for deterministic sorting, safe field filtering, structured-mode prompt injection, structured-mode normalization, and flag-off backward compatibility.
- During greening, I tightened the flag-off test with a `get_relevant_memory` monkeypatch so memory state could not make the assertion flaky.

## Full-suite result

Command:

```powershell
python -m pytest -q
```

Output:

```text
296 passed, 1 skipped, 1 warning in 14.63s
```

Warning observed:

```text
DeprecationWarning in tests/test_embeddings_gemini.py from google.genai.types.py
```

This warning is pre-existing and unrelated to the planner change.

## Self-review

### Scope check

- Only planner and planner tests were changed for behavior.
- No executor/main/server/MCP transport/Compose changes were made.
- Structured behavior remains false-by-default unless enabled by flag or explicit keyword argument.

### Contract check

- `plan_task(prompt, user_id, llm)` remains valid.
- Structured mode uses injected `tool_specs` when supplied; otherwise defaults to `get_capability_registry().list_specs()`.
- Structured-mode output is normalized through `normalize_plan_items(...)`.
- Non-structured mode returns the original `llm.plan(...)` result unchanged.

### Safety check

- Catalog output is deterministic by `spec.name`.
- Catalog includes only `name`, `description`, `input_schema`, `side_effects`, and `idempotent`.
- Input schema is recursively reduced to structural JSON-schema keys so prompt output excludes `plugin_id`, URL/env-bearing descriptions, and other sensitive metadata fields.

## Concerns

- The input-schema sanitizer is intentionally conservative. If later tasks need richer schema annotations in prompts (for example `description`, `format`, or examples), that should be added deliberately with its own safety review instead of broadening this task implicitly.

---

## Review follow-up: Task 2 review findings fixed on 2026-08-09

### Root cause

- `_sanitize_input_schema(...)` previously kept raw `properties` names and passed scalar `enum` / `const` values through unchanged.
- That allowed sensitive property names such as `headers_env` plus environment-variable, URL, and command-like scalar values to enter the planner prompt even though the prompt contract forbids them.

### Minimal fix

- Filter sensitive schema property names recursively while preserving safe property names and deterministic ordering.
- Filter `required` entries so removed sensitive properties cannot survive there.
- Redact sensitive scalar `enum` / `const` values to a stable `[REDACTED]` placeholder while preserving safe scalar choices.
- Kept the change scoped to `src/agent/planner.py` and `tests/test_planner.py`.

### RED regression reproduction

Command:

```powershell
python -m pytest tests/test_planner.py -q
```

Output:

```text
........F..
FAILED tests/test_planner.py::test_build_tool_catalog_prompt_redacts_sensitive_schema_names_and_scalar_values
AssertionError: assert 'headers_env' not in 'Tool catalog: ...'
1 failed, 10 passed in 0.44s
```

### Focused verification

Command:

```powershell
python -m pytest tests/test_planner.py tests/test_llm.py -q
```

Output:

```text
27 passed in 0.42s
```

### Full-suite verification

Command:

```powershell
python -m pytest -q
```

Output:

```text
297 passed, 1 skipped, 1 warning in 14.45s
```

Warning observed:

```text
DeprecationWarning in tests/test_embeddings_gemini.py from google.genai.types.py
```

This warning remained pre-existing and unrelated to the planner sanitizer change.
