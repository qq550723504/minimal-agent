# OpenAI SDK 统一与 Provider Contract Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LLM 和 Embeddings adapter 统一到 OpenAI 新版 `OpenAI` client，并用不访问真实网络的 provider-shaped fake client contract tests 锁定请求和响应契约。

**Architecture:** 两个 adapter 都接受可选的 `client` 依赖；生产路径在缺少注入 client 时从 `OPENAI_API_KEY` 构造 `OpenAI`，测试路径注入带有 `chat.completions` 或 `embeddings` 资源的 fake client。LLM 与 Embeddings 保持各自已有业务接口，只替换 provider 边界和响应读取方式。

**Tech Stack:** Python 3.11+, OpenAI Python SDK 1.x client API, pytest, existing `LLMAdapter` and `EmbeddingAdapter` interfaces.

## Global Constraints

- 不发起真实 OpenAI 网络请求。
- 不向 `openai` 模块全局写入 `api_key`。
- 继续从 `OPENAI_API_KEY` 读取配置，缺失时保留现有 `ValueError`。
- 继续保留 provider SDK 缺失时的明确 `RuntimeError`。
- 保留现有 LLM 计划解析和 echo fallback 语义。
- 只修改 OpenAI adapter、相关测试、依赖和本次设计/计划文档。

---

### Task 1: Replace legacy LLM test with a failing v1 client contract test

**Files:**
- Modify: `tests/test_llm_openai.py`
- Test target: `src/agent/llm_openai.py`

**Interfaces:**
- Consumes: `OpenAIAdapter(model, client)` planned constructor and `client.chat.completions.create` resource shape.
- Produces: A regression test that fails against the current `openai.ChatCompletion.create` implementation.

- [ ] **Step 1: Write the failing test**

Replace the module-level monkeypatch with provider-shaped fakes:

```python
class FakeChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": "第一句。第二句?"})()},
                    )
                ]
            },
        )()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


def test_openai_adapter_uses_v1_chat_client_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    client = FakeOpenAIClient()

    from src.agent.llm_openai import OpenAIAdapter

    adapter = OpenAIAdapter(model="dummy-model", client=client)

    assert adapter.plan("任何提示") == ["echo: 第一句", "echo: 第二句"]
    assert client.chat.completions.calls == [
        {
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "任何提示"}],
            "max_tokens": 512,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_openai.py::test_openai_adapter_uses_v1_chat_client_contract -q`

Expected: FAIL because the current adapter does not accept `client` and still calls the legacy `ChatCompletion` API.

### Task 2: Implement the minimal v1 LLM client adapter

**Files:**
- Modify: `src/agent/llm_openai.py`
- Test: `tests/test_llm_openai.py`

**Interfaces:**
- Consumes: Task 1 fake client contract.
- Produces: `OpenAIAdapter.__init__(model: Optional[str] = None, client: Optional[Any] = None)` and v1 chat completion calls.

- [ ] **Step 1: Write the minimal implementation**

Import `OpenAI` from the SDK inside the constructor, keep the existing API-key validation, and construct the client only when one was not injected:

```python
from openai import OpenAI

def __init__(self, model=None, client=None):
    self.api_key = os.getenv("OPENAI_API_KEY")
    if not self.api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    self._client = client or OpenAI(api_key=self.api_key)
    self.model = model or "gpt-3.5-turbo"
```

Call `self._client.chat.completions.create(...)`, then read `resp.choices[0].message.content`. Preserve the existing parsing and fallback code unchanged.

- [ ] **Step 2: Run the focused test to verify it passes**

Run: `python -m pytest tests/test_llm_openai.py -q`

Expected: PASS with the v1 client contract test and no network access.

- [ ] **Step 3: Run the existing LLM tests**

Run: `python -m pytest tests/test_llm.py tests/test_llm_openai.py -q`

Expected: PASS with no legacy `ChatCompletion` references in the provider test.

### Task 3: Add and satisfy the Embeddings v1 client contract

**Files:**
- Modify: `tests/test_embeddings_factory.py` or create `tests/test_embeddings_openai.py`
- Modify: `src/agent/embeddings_openai.py`

**Interfaces:**
- Consumes: `OpenAIEmbeddingAdapter(model, client)` and `client.embeddings.create`.
- Produces: A fake-client contract test and an adapter that uses the same injected-client boundary as the LLM adapter.

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings_openai.py` with this behavior:

```python
def test_openai_embedding_adapter_uses_v1_embeddings_client_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    client = FakeEmbeddingClient()

    from src.agent.embeddings_openai import OpenAIEmbeddingAdapter

    adapter = OpenAIEmbeddingAdapter(model="dummy-embedding", client=client)

    assert adapter.embed("hello") == [0.1, 0.2, 0.3]
    assert client.embeddings.calls == [
        {"model": "dummy-embedding", "input": "hello"}
    ]
```

`FakeEmbeddingClient` must expose `embeddings.create(**kwargs)` and return an object with `data[0].embedding == [0.1, 0.2, 0.3]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_embeddings_openai.py::test_openai_embedding_adapter_uses_v1_embeddings_client_contract -q`

Expected: FAIL because the current adapter does not accept an injected client.

- [ ] **Step 3: Write the minimal implementation**

Import `OpenAI`, add `client=None`, validate `OPENAI_API_KEY`, set `self._client = client or OpenAI(api_key=...)`, call `self._client.embeddings.create(model=self._model, input=text)`, and return `resp.data[0].embedding`.

- [ ] **Step 4: Run focused embedding tests**

Run: `python -m pytest tests/test_embeddings_openai.py tests/test_embeddings_factory.py -q`

Expected: PASS with no writes to `openai.api_key` and no network access.

### Task 4: Update the SDK dependency and validate the complete change

**Files:**
- Modify: `requirements.txt`
- Test: `tests/test_llm_openai.py`
- Test: `tests/test_embeddings_openai.py`
- Test: `tests/test_embeddings_factory.py`

**Interfaces:**
- Consumes: Both v1 client adapters from Tasks 2 and 3.
- Produces: A dependency declaration compatible with `OpenAI(api_key=...)` and a repository-wide verified change.

- [ ] **Step 1: Update the dependency pin**

Change `openai==1.0.0` to `openai==1.58.1`, a 1.x release supporting the client/resource API used by both adapters.

- [ ] **Step 2: Check the dependency and source contract**

Run: `rg -n "ChatCompletion|openai\.api_key|client\.chat\.completions|client\.embeddings|openai==" src tests requirements.txt`

Expected: no legacy `ChatCompletion` or module-global `openai.api_key` references; both adapters and tests use the v1 client/resource contract.

- [ ] **Step 3: Run all provider and factory tests**

Run: `python -m pytest tests/test_llm_openai.py tests/test_embeddings_openai.py tests/test_embeddings_factory.py -q`

Expected: all focused tests pass.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest -q`

Expected: all tests pass with only the repository's existing deprecation warnings, if any.

- [ ] **Step 5: Review the diff and commit implementation**

Run: `git diff --check; git diff --stat; git status --short`

Stage only `src/agent/llm_openai.py`, `src/agent/embeddings_openai.py`, `tests/test_llm_openai.py`, `tests/test_embeddings_openai.py`, and `requirements.txt`, then commit:

```bash
git add src/agent/llm_openai.py src/agent/embeddings_openai.py tests/test_llm_openai.py tests/test_embeddings_openai.py requirements.txt
git commit -m "feat: unify OpenAI client adapters"
```
