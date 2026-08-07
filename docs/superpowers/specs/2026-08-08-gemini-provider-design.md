# Gemini LLM 与 Embeddings Provider 设计

## 目标

在现有 OpenAI/mock provider 架构中增加 Gemini LLM 和 Gemini Embeddings 支持，让用户可以通过环境变量切换后端，同时保持 Planner、向量记忆和任务执行层的接口不变。

## SDK 与模型

- 使用 Google 官方 `google-genai` Python SDK，不使用已经弃用的旧 `google-generativeai` 包。
- Gemini LLM 默认模型：`gemini-2.5-flash`，可由 `GEMINI_MODEL` 覆盖。
- Gemini Embeddings 默认模型：`gemini-embedding-2`，可由 `GEMINI_EMBEDDING_MODEL` 覆盖。
- API Key 从 `GEMINI_API_KEY` 读取。

## 适配器边界

新增两个适配器：

```python
GeminiAdapter(model=None, client=None)
GeminiEmbeddingAdapter(model="gemini-embedding-2", client=None)
```

未注入 client 时，生产代码使用 `genai.Client(api_key=...)` 创建客户端；测试通过注入 fake client，禁止真实网络请求。LLM 调用 `client.models.generate_content(model=..., contents=...)`，从 `response.text` 读取文本。Embeddings 调用 `client.models.embed_content(model=..., contents=...)`，从 `response.embeddings[0].values` 读取向量。

两个 adapter 都保留现有缺少 API key 和 SDK 缺失时的明确错误语义，并将 provider 异常交给上层处理，不在 adapter 内添加重试或吞错。

## 配置与工厂

- `AGENT_LLM_BACKEND=gemini` 创建 `GeminiAdapter`。
- `AGENT_EMBEDDING_BACKEND=gemini` 创建 `GeminiEmbeddingAdapter`。
- `AGENT_LLM_BACKEND` 和 `AGENT_EMBEDDING_BACKEND` 仍默认使用 `mock`。
- `openai`、`gemini` 和 `mock` 三种后端都保持互不影响。
- README 增加 Gemini 环境变量和使用示例。

## 向量记忆兼容性

Gemini Embeddings 与 OpenAI/mock 的向量空间和维度不保证兼容；切换到 Gemini Embeddings 后，已有 `VECTOR_MEMORY_PATH` 数据应删除或重新生成。代码不自动混用不同 provider 的旧向量，也不在本次改动中设计迁移算法。

## 测试

- Gemini LLM contract test 验证 fake client 收到 model、contents，并验证 `.text` 被解析为步骤。
- Gemini Embeddings contract test 验证 fake client 收到 model、contents，并验证 `.embeddings[0].values` 被转换为 `List[float]`。
- Factory tests 验证 `gemini` 后端选择正确的 adapter。
- Contract tests 不导入真实网络 transport，不需要 API Key 之外的外部服务。
- 运行 Gemini focused tests 和完整 pytest。
