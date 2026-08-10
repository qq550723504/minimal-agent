# Qwen LLM Support Design

## Goal

Add Alibaba Cloud Model Studio (DashScope) Qwen support for the project's
conversation and planning LLM. Embedding support is explicitly out of scope.

## Approach

Add a dedicated `qwen` LLM backend and adapter. The adapter uses DashScope's
OpenAI-compatible Chat Completions endpoint through the existing `openai`
Python dependency. This keeps the Qwen integration consistent with the
existing `OpenAIAdapter` while giving Qwen its own credential and configuration
names.

The default deployment targets the Beijing DashScope compatible endpoint:

`https://dashscope.aliyuncs.com/compatible-mode/v1`

The endpoint remains configurable for a Model Studio workspace or another
region.

## Configuration

The following environment variables will be added:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_LLM_BACKEND` | `mock` | Accepts `qwen` to select the adapter. |
| `DASHSCOPE_API_KEY` | none | Required API key for the Qwen adapter. |
| `QWEN_MODEL` | `qwen-plus` | Chat model to invoke. |
| `DASHSCOPE_BASE_URL` | Beijing compatible endpoint | Override for another region or workspace endpoint. |

No Qwen embedding backend or embedding-related variables will be added.

## Components and Data Flow

1. `config.py` reads the Qwen model and compatible API base URL.
2. `llm_factory.py` recognizes `AGENT_LLM_BACKEND=qwen` and constructs
   `QwenAdapter` with `QWEN_MODEL`.
3. `QwenAdapter` reads `DASHSCOPE_API_KEY`, builds an OpenAI client with
   `base_url=DASHSCOPE_BASE_URL`, and calls `chat.completions.create`.
4. The adapter parses the returned text with the existing `parse_plan_output`
   helper, retaining the behavior of other LLM adapters: textual plan items
   receive the `echo: ` prefix, structured items are returned unchanged, and an
   empty response produces an empty plan.

The planner and executor require no changes because they already consume the
common `LLMAdapter` contract.

## Errors

- Missing `DASHSCOPE_API_KEY` raises a clear `ValueError` before a network call.
- An unavailable `openai` package raises a clear `RuntimeError`, matching the
  existing OpenAI adapter behavior.
- Provider or network errors are not swallowed; the existing caller receives
  the SDK error.

## Verification

Add isolated unit tests using a fake OpenAI-compatible client to verify:

- The adapter supplies the configured model and user message to Chat
  Completions.
- The client receives the DashScope base URL when the adapter creates it.
- Empty output produces an empty plan.
- The factory selects `QwenAdapter` when the backend is `qwen`.

Update deployment configuration tests and README documentation to cover the
new environment variables. Run the focused Qwen tests and the full test suite.

## Out of Scope

- DashScope native SDK integration.
- Qwen embedding models.
- Tool calling, web search, thinking mode, streaming, multimodal inputs, and
  automatic retries.
