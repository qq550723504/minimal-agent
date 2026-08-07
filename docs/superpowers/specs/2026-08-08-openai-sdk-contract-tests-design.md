# OpenAI SDK 统一与 Provider Contract Tests 设计

## 目标

统一 LLM 和 Embeddings 适配器到 OpenAI 新版 SDK 的 client 调用方式，并让两个适配器都支持注入 fake client，以便用 provider 形态的 mock contract tests 验证请求参数和响应解析，而不访问真实 OpenAI 网络。

## 现状与边界

- `OpenAIAdapter` 当前使用旧的 `openai.ChatCompletion.create` 模块级接口。
- `OpenAIEmbeddingAdapter` 当前使用新版资源接口，但仍依赖模块级 `openai.api_key`。
- 本次只改 OpenAI provider 边界、依赖声明和对应测试，不修改 Planner、向量存储或任务执行流程。
- 测试禁止真实网络请求；fake client 必须模拟新版 SDK 的对象响应结构。

## 推荐方案

两个 adapter 统一使用 `from openai import OpenAI` 创建 client，并提供可选的 `client` 构造参数：

```python
OpenAIAdapter(model=None, client=None)
OpenAIEmbeddingAdapter(model="text-embedding-3-small", client=None)
```

未传入 client 时，adapter 从 `OPENAI_API_KEY` 创建 `OpenAI(api_key=...)`；测试传入 fake client。LLM 调用 `client.chat.completions.create(...)`，Embeddings 调用 `client.embeddings.create(...)`。这样 API key 不再写入 SDK 模块全局状态，两个 provider 具有一致的依赖注入边界。

## 数据流与响应处理

1. adapter 初始化时校验 API key；若传入 fake client，则仍要求环境变量存在，保持现有配置错误语义。
2. LLM 以 `model`、一条 user message 和 `max_tokens=512` 调用 chat completions。
3. LLM 从新版响应对象的 `choices[0].message.content` 读取文本，并复用现有 `parse_plan_output` 与 echo fallback。
4. Embeddings 以 `model` 和 `input=text` 调用 embeddings endpoint。
5. Embeddings 从新版响应对象的 `data[0].embedding` 返回浮点数组。

为兼容 OpenAI SDK 的 typed objects 与简单 fake，响应读取使用属性访问；测试 fake 也提供对应属性，不再 monkeypatch 已废弃的类级 API。

## 错误处理

- 缺少 `OPENAI_API_KEY` 继续抛出现有 `ValueError`。
- OpenAI SDK 未安装继续抛出 provider-specific `RuntimeError`。
- SDK API 异常不在 adapter 内吞掉，交给现有上层任务错误处理。
- 响应为空或不符合预期时保留自然的索引/属性错误，不添加无需求的重试或降级逻辑。

## 测试设计

- LLM contract test：验证新版 chat client 收到精确的 model、messages、max_tokens，并验证对象响应被解析为步骤。
- Embeddings contract test：验证新版 embeddings client 收到精确的 model、input，并验证对象响应被解析为向量。
- 两个 adapter 都覆盖 client 注入，确保测试不触碰真实 SDK 网络或模块全局 key。
- 保留 API key 缺失和 SDK 缺失的现有错误行为测试（必要时改为注入/patch `OpenAI` 构造器）。
- 运行 provider tests、完整 pytest 和依赖配置检查。

## 依赖策略

将 `requirements.txt` 的 OpenAI 依赖从 `1.0.0` 提升到一个明确支持 `OpenAI` client 及 typed response 的新版 1.x 版本；代码不依赖 2.x 独有功能。
