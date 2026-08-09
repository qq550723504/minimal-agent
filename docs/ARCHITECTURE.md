# Agent 架构设计

本文件描述项目中的主要模块、接口契约与扩展点，供实现与评审参考。

## 模块划分
- `Perception/API`：FastAPI 路由接收同步请求、队列请求和目录查询，统一执行 API Key 鉴权、用户隔离与输入清理。
- `Memory`：短期/长期记忆层，向量记忆按用户隔离并持久化到 `VECTOR_MEMORY_PATH`。
- `Planner`：核心决策引擎，将高层目标分解为有序步骤（子任务）。
- `Executor/CapabilityRegistry`：统一执行本地、插件和 MCP 工具；验证 JSON Schema、施加执行 timeout、结果大小限制，并区分可重试错误与 `unknown_outcome`。
- `Skills`：从已验证插件构建确定性 Skill 目录，按显式 ID 或触发词选择 Skill；参考文件只能从 Skill 根目录内读取。
- `Plugins`：读取并校验 `plugin.yaml`，检查路径、链接/junction、声明重复和清单契约；插件按 enabled/required 语义加载。
- `MCP`：`MCPClientManager` 持有 SDK 客户端和 `AsyncExitStack` 生命周期；stdio 与 Streamable HTTP 使用独立安全验证和 allowlist。
- `Tools`：本地工具、HTTP 工具和 MCP 工具适配器，统一注册到能力目录并暴露安全元数据。
- `Safety/Observability`：输入/输出过滤、SSRF/DNS 固定、shell 边界、审计日志、Prometheus 指标和稳定错误码。

## 接口契约
- `/api/handle` 接收 `{ "prompt": "..." }` 并同步返回 `{ "result": "..." }`；`/api/handle/queue` 返回任务状态。
- `/api/tasks`、`/api/tools`、`/api/plugins`、`/api/skills` 返回当前用户可见的任务、工具和运行时目录元数据。
- 能力调用使用 `ToolCall`、`ToolSpec` 和 `ToolResult`；结果状态为 `success`、`error` 或 `unknown_outcome`，并携带稳定 `error_code` 与 `retryable`。
- 插件清单采用 `minimal-agent/v1`；MCP 工具名按插件/Server/远端工具分段命名，含点号的分段会编码避免碰撞。

## 扩展点
- 插件化 Planner（策略模式）以支持多模型/规则引擎。
- Memory 抽象以支持向量检索或关系型存储。
- 新插件通过 `plugin.yaml` 声明 Skill 和 MCP allowlist，不需要修改核心注册代码。

## 运行时启动流程

```text
请求/API Key
    -> 输入清理与用户隔离
    -> Planner 生成步骤
    -> ToolCall
    -> CapabilityRegistry 校验参数/timeout 并分发
    -> 本地工具处理器或插件 MCP 客户端
    -> 规范化 ToolResult
    -> 结果大小检查与稳定错误状态
    -> Executor 继续后续步骤或返回同步响应/持久化队列状态
```

应用 lifespan 启动时加载插件、建立 Skill 目录、启动 MCP 客户端并注册工具；关闭时按逆序停止队列、清理 MCP 连接、注销运行时工具并保存记忆。必需插件启动失败会阻止服务，普通插件只记录禁用状态。结构化工具调用的首个切片仅在 `/api/handle` 请求路径上把 `ToolCall` 送入 `CapabilityRegistry`；SQLite 队列路径仍保留旧的字符串步骤执行语义。

## 性能与可用性考虑
- 关键路径支持异步执行与限流；同步工具和 Schema 校验在线程边界内执行并受 timeout 约束。
- MCP 工具发现限制分页总时间、游标循环、工具数量和累计大小；HTTP 响应使用固定地址和响应大小边界。
- 将长时间运行任务交由当前 SQLite 持久化任务队列异步处理；跨进程恢复仅适用于工作流入口创建的任务。
