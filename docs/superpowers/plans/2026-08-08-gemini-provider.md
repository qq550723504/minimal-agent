# Gemini LLM 与 Embeddings Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 provider 架构中增加 Gemini LLM、Gemini Embeddings、factory 路由、配置和 mock contract tests。

**Architecture:** 新增两个独立 adapter，分别实现 `LLMAdapter` 和 `EmbeddingAdapter`。生产路径使用 `google.genai.Client(api_key=...)`，测试路径注入 fake client；factory 根据 `AGENT_LLM_BACKEND` 和 `AGENT_EMBEDDING_BACKEND` 在 mock、OpenAI、Gemini 之间选择，不改业务层接口。

**Tech Stack:** Python 3.11+, `fastapi==0.141.1`, `pydantic==2.13.4`, `httpx==0.28.1`, `google-genai==2.17.0`, pytest, existing adapter/factory interfaces.

## Global Constraints

- 不发起真实 Gemini 网络请求。
- 不使用旧版 `google-generativeai` SDK。
- 继续从 `GEMINI_API_KEY` 读取配置，缺失时抛出明确 `ValueError`。
- 默认后端仍为 `mock`，现有 OpenAI 路径必须保持兼容。
- FastAPI/Pydantic/httpx 升级后必须通过完整服务测试。
- Gemini Embeddings 默认使用 `gemini-embedding-2`；切换 provider 时不混用旧向量。

---

### Task 1: Add failing Gemini LLM provider contract test

**Files:**
- Create: `tests/test_llm_gemini.py`
- Test target: `src/agent/llm_gemini.py`

**Interfaces:**
- Consumes: `GeminiAdapter(model, client)` and `client.models.generate_content`.
- Produces: A test that proves request arguments and `.text` response parsing.

- [ ] **Step 1: Write the failing test**

Create a fake client whose `models.generate_content` records keyword arguments and returns an object with `text == "第一句。第二句?"`:

```python
def test_gemini_adapter_uses_generate_content_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = FakeGeminiClient()

    from src.agent.llm_gemini import GeminiAdapter

    adapter = GeminiAdapter(model="gemini-test", client=client)

    assert adapter.plan("任何提示") == ["echo: 第一句", "echo: 第二句"]
    assert client.models.calls == [
        {"model": "gemini-test", "contents": "任何提示"}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_gemini.py::test_gemini_adapter_uses_generate_content_contract -q`

Expected: FAIL because `src/agent/llm_gemini.py` and `GeminiAdapter` do not exist.

### Task 2: Implement Gemini LLM adapter

**Files:**
- Create: `src/agent/llm_gemini.py`
- Test: `tests/test_llm_gemini.py`

**Interfaces:**
- Consumes: Task 1 fake client.
- Produces: `GeminiAdapter(LLMAdapter)` with `plan(prompt) -> List[Any]`.

- [ ] **Step 1: Write the minimal implementation**

Use lazy import and client injection:

```python
from google import genai

def __init__(self, model=None, client=None):
    self.api_key = os.getenv("GEMINI_API_KEY")
    if not self.api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    self._client = client if client is not None else genai.Client(api_key=self.api_key)
    self.model = model or "gemini-2.5-flash"
```

Call `self._client.models.generate_content(model=self.model, contents=prompt)`, read `response.text`, and reuse `parse_plan_output` plus the existing echo fallback from `OpenAIAdapter`.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_llm_gemini.py tests/test_llm.py -q`

Expected: PASS without a real Gemini API key or network call.

### Task 3: Add and implement Gemini Embeddings contract

**Files:**
- Create: `tests/test_embeddings_gemini.py`
- Create: `src/agent/embeddings_gemini.py`

**Interfaces:**
- Consumes: `GeminiEmbeddingAdapter(model, client)` and `client.models.embed_content`.
- Produces: `embed(text) -> List[float]` from `response.embeddings[0].values`.

- [ ] **Step 1: Write the failing test**

Use a fake client with `models.embed_content(**kwargs)` recording calls and returning an object with `embeddings[0].values == [0.1, 0.2, 0.3]`:

```python
def test_gemini_embedding_adapter_uses_embed_content_contract(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    client = FakeGeminiClient()

    from src.agent.embeddings_gemini import GeminiEmbeddingAdapter

    adapter = GeminiEmbeddingAdapter(model="gemini-embedding-test", client=client)

    assert adapter.embed("hello") == [0.1, 0.2, 0.3]
    assert client.models.calls == [
        {"model": "gemini-embedding-test", "contents": "hello"}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_embeddings_gemini.py::test_gemini_embedding_adapter_uses_embed_content_contract -q`

Expected: FAIL because `GeminiEmbeddingAdapter` does not exist.

- [ ] **Step 3: Write the minimal implementation**

Use lazy `from google import genai`, validate `GEMINI_API_KEY`, construct `genai.Client(api_key=...)` only when no client is injected, call `self._client.models.embed_content(model=self._model, contents=text)`, and return `response.embeddings[0].values`.

- [ ] **Step 4: Run focused embedding tests**

Run: `python -m pytest tests/test_embeddings_gemini.py tests/test_embeddings_factory.py -q`

Expected: PASS without network access.

### Task 4: Route factories, add configuration, dependency, and documentation

**Files:**
- Modify: `src/agent/config.py`
- Modify: `src/agent/llm_factory.py`
- Modify: `src/agent/embeddings_factory.py`
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `tests/test_embeddings_factory.py`
- Create: `tests/test_gemini_factory.py`

**Interfaces:**
- Consumes: `GeminiAdapter` and `GeminiEmbeddingAdapter` from Tasks 2 and 3.
- Produces: `gemini` backend selection and documented environment variables.

- [ ] **Step 1: Add failing factory tests**

Patch factory module constants in tests and assert the returned class names:

```python
def test_create_llm_adapter_selects_gemini(monkeypatch):
    import src.agent.llm_factory as factory
    monkeypatch.setattr(factory, "LLM_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    assert factory.create_llm_adapter().__class__.__name__ == "GeminiAdapter"


def test_create_embedding_adapter_selects_gemini(monkeypatch):
    import src.agent.embeddings_factory as factory
    monkeypatch.setattr(factory, "EMBEDDING_BACKEND", "gemini")
    monkeypatch.setattr(factory, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-test")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    assert factory.create_embedding_adapter().__class__.__name__ == "GeminiEmbeddingAdapter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gemini_factory.py -q`

Expected: FAIL because factory constants and `gemini` branches do not exist.

- [ ] **Step 3: Add configuration and factory branches**

Add `GEMINI_MODEL` and `GEMINI_EMBEDDING_MODEL` to `src/agent/config.py`; import them in the respective factories; branch on `backend == "gemini"` and construct the matching adapter.

- [ ] **Step 4: Update dependency and README**

Update `requirements.txt` to `fastapi==0.141.1`, `pydantic==2.13.4`, `httpx==0.28.1`, and add `google-genai==2.17.0`. Document `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`, and both `AGENT_*_BACKEND=gemini` settings. Add a warning that changing embedding providers requires rebuilding vector memory.

- [ ] **Step 5: Run factory and deployment/config tests**

Run: `python -m pytest tests/test_gemini_factory.py tests/test_embeddings_factory.py tests/test_deployment_config.py -q`

Expected: PASS.

### Task 5: Full verification and commit

**Files:**
- Test: `tests/test_llm_gemini.py`
- Test: `tests/test_embeddings_gemini.py`
- Test: `tests/test_gemini_factory.py`

- [ ] **Step 1: Install the new dependency**

Run: `python -m pip install google-genai==2.17.0`

Expected: the official SDK is importable as `from google import genai`.

- [ ] **Step 2: Check source and dependency references**

Run: `rg -n "google-generativeai|google-genai|GEMINI|backend == \"gemini\"" src tests README.md requirements.txt`

Expected: only the new `google-genai` SDK and documented Gemini configuration are present.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -q`

Expected: all tests pass with only existing deprecation warnings, if any.

- [ ] **Step 4: Review diff and commit**

Run: `git diff --check; git diff --stat; git status --short`

Stage only the Gemini source, tests, config, factory, requirements, and README files, then commit:

```bash
git add src/agent/llm_gemini.py src/agent/embeddings_gemini.py src/agent/config.py src/agent/llm_factory.py src/agent/embeddings_factory.py tests/test_llm_gemini.py tests/test_embeddings_gemini.py tests/test_gemini_factory.py tests/test_embeddings_factory.py requirements.txt README.md
git commit -m "feat: add Gemini LLM and embedding providers"
```
