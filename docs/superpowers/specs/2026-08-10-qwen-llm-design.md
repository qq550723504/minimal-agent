# OpenAI-Compatible LLM Support Design

## Goal

Add a generic OpenAI-compatible backend for the project's conversation and
planning LLM, with Alibaba Cloud Model Studio (DashScope) Qwen as a named
convenience preset. Embedding support is explicitly out of scope.

## Approach

Extract a reusable `OpenAICompatibleAdapter` for providers that implement the
OpenAI Chat Completions contract. Keep `OpenAIAdapter` as the existing OpenAI
configuration, and configure the `qwen` backend through the same reusable
adapter with provider-specific credentials, endpoint, and model settings.
Expose `openai-compatible` for arbitrary compatible providers and retain
`qwen` as a preset with DashScope defaults. Gemini continues to use its native
adapter because it does not use this contract.

The default deployment targets the Beijing DashScope compatible endpoint:

`https://dashscope.aliyuncs.com/compatible-mode/v1`

The endpoint remains configurable for a Model Studio workspace or another
region.

## Configuration

The following environment variables will be added:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_LLM_BACKEND` | `mock` | Accepts `openai-compatible` for arbitrary compatible providers or `qwen` for the DashScope preset. |
| `OPENAI_COMPATIBLE_API_KEY` | none | API key for the generic compatible backend. |
| `OPENAI_COMPATIBLE_BASE_URL` | none | Base URL for the generic compatible backend. |
| `OPENAI_COMPATIBLE_MODEL` | none | Model identifier for the generic compatible backend. |
| `DASHSCOPE_API_KEY` | none | Required API key for the Qwen adapter. |
| `QWEN_MODEL` | `qwen-plus` | Chat model to invoke. |
| `DASHSCOPE_BASE_URL` | Beijing compatible endpoint | Override for another region or workspace endpoint. |

No Qwen embedding backend or embedding-related variables will be added.

## Components and Data Flow

1. `config.py` reads generic compatible settings and Qwen preset settings.
2. `llm_factory.py` recognizes `AGENT_LLM_BACKEND=openai-compatible` or
   `qwen` and constructs `OpenAICompatibleAdapter` with the corresponding
   environment variables, model, and base URL.
3. `OpenAICompatibleAdapter` builds an OpenAI client and calls
   `chat.completions.create` using the provider configuration.
4. The shared adapter parses returned text with the existing `parse_plan_output`
   helper, retaining the behavior of other LLM adapters: textual plan items
   receive the `echo: ` prefix, structured items are returned unchanged, and an
   empty response produces an empty plan.

The planner and executor require no changes because they already consume the
common `LLMAdapter` contract.

## Errors

- Missing the configured API-key environment variable raises a clear `ValueError`
  before a network call.
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
- The factory selects the shared adapter with generic configuration when the
  backend is `openai-compatible`.
- The factory selects the shared adapter with DashScope configuration when the
  backend is `qwen`.

Update deployment configuration tests and README documentation to cover both
the generic backend and the Qwen preset. Run focused adapter/factory tests and
the full test suite.

## Out of Scope

- DashScope native SDK integration.
- Qwen embedding models.
- Tool calling, web search, thinking mode, streaming, multimodal inputs, and
  automatic retries.
