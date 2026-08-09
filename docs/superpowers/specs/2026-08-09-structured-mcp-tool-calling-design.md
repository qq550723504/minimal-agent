# MCP 结构化工具调用闭环设计

## 1. 背景

当前项目已经具备 MCP Server 生命周期管理、工具发现、工具清单校验、能力注册、JSON Schema 校验、超时、结果大小限制和安全错误状态。

但自然语言主链路仍以旧的字符串步骤执行为主：

```text
请求 -> Planner -> execute_tasks -> execute_step
```

MCP 工具主要注册在 `CapabilityRegistry`，而 `execute_step` 的旧分支通过本地 legacy tool registry 查找工具。因此，MCP 工具可以被发现和注册，但还没有稳定接入普通 `/api/handle` 的自然语言执行链路。

本设计只解决通用 Agent Runtime 的结构化工具调用问题，为后续智慧园区能耗 MCP 接入提供基础，不实现能耗领域业务。

## 2. 目标与非目标

### 目标

- 让 Planner 能看到当前已注册、可调用的工具元数据。
- 让模型输出可验证的结构化工具调用。
- 让结构化调用统一经过 `CapabilityRegistry.invoke()`。
- 让本地工具和 MCP 工具使用同一套参数校验、超时、结果大小和错误状态。
- 保留现有 Mock、echo、`http_get`、`http_post` 和旧字符串步骤的兼容行为。
- 在 API 请求链路中传递用户、运行和 Skill 上下文，并记录安全审计信息。
- 使用 fake MCP Server 和 provider fake client 覆盖核心契约，不依赖真实能耗系统或真实模型网络。

### 非目标

- 不实现能耗数据采集、时序数据库、指标口径、账单或设备控制。
- 不重写现有 MCP transport 和安全校验。
- 不在本阶段实现 MCP 工具的设备写操作审批流。
- 不把异步 SQLite 工作流队列改造成 MCP 专用异步队列；首期只保证 HTTP 请求链路支持结构化 MCP 调用。旧队列行为保持不变。
- 不要求模型供应商的原生 function calling；首期使用统一的结构化 JSON 规划契约，以兼容 Mock、OpenAI 和 Gemini。

## 3. 方案选择

### 方案 A：提示词约束的统一结构化规划（采用）

在 Planner 提示中注入安全工具目录和 JSON 输出契约，要求模型返回文本步骤或结构化 `tool_call` 对象。通过统一解析器将结果转换为内部计划项，再由执行器分流到 legacy 或 CapabilityRegistry。

优点是兼容当前三种 LLM 后端、改动边界清晰、可使用现有 fake-client 测试；缺点是依赖模型遵守 JSON 契约，需要对解析失败和未知工具做安全降级。

### 方案 B：为每个 LLM 后端实现原生 function calling

分别使用 OpenAI 和 Gemini 的原生工具调用接口，并为 Mock 增加模拟协议。

优点是模型侧约束更强；缺点是 provider API 差异大，会把供应商协议泄漏到 Planner，增加测试和迁移成本，不适合作为当前框架的第一步。

### 方案 C：由外部能耗 MCP Gateway 完成 Agent 编排

minimal-agent 只做 MCP 代理，不负责工具选择和结构化执行。

优点是 Agent 侧改动小；缺点是削弱当前项目的通用编排能力，权限、审计和错误语义会分散到外部系统，不符合当前 Runtime 的定位。

## 4. 设计

### 4.1 内部计划项

增加平台中立的计划项语义，至少支持两类：

- 文本步骤：继续支持现有字符串和 `echo:` 行为。
- 工具调用步骤：包含 `call_id`、工具名和 JSON 对象参数。

工具调用步骤必须经过 Pydantic 模型校验；不接受未知字段、空工具名、非对象参数或无法解析的结构化内容。

模型返回的顶层格式为 JSON 数组。数组元素可以是字符串，也可以是：

```json
{
  "kind": "tool_call",
  "call_id": "call-1",
  "tool": "energy.query_trend",
  "arguments": {
    "park_id": "park-a",
    "start": "2026-08-01",
    "end": "2026-08-31"
  }
}
```

解析失败时保持现有文本分句回退，不把任意模型文本当作工具调用执行。

### 4.2 工具目录注入

Planner 从 `CapabilityRegistry.list_specs()` 获取工具元数据，只注入以下字段：

- `name`
- `description`
- `input_schema`
- `side_effects`
- `idempotent`

不注入 MCP URL、命令、环境变量、认证信息或 Skill 正文。目录排序必须稳定，避免模型提示和测试结果随机变化。

首期只向 API 请求链路注入当前 Runtime 已注册的能力；能力目录为空时，Planner 仍按原有文本规划工作。

### 4.3 执行桥接

在执行层增加结构化计划执行入口：

```text
计划项
├─ 文本步骤 -> 现有 execute_step
└─ 工具调用 -> ToolCall -> CapabilityRegistry.invoke -> ToolResult
```

结构化工具调用严格按计划顺序执行，不并发执行同一请求中的调用。每次调用使用当前用户的 `ToolInvocationContext`，至少包含：

- `owner_id`
- `run_id`
- `active_skill_ids`

工具结果统一保留 `status`、`error_code`、`retryable` 和 `content`。MCP 返回的未知结果不得被转化为成功结果。

由于 MCP SDK 客户端和 `AsyncExitStack` 由 FastAPI lifespan 管理，API 工具调用链路改为异步执行，确保调用使用同一个应用生命周期。同步 CLI/legacy 入口继续保留兼容包装，但不复用正在运行的异步事件循环。

### 4.4 API 行为

`POST /api/handle` 继续返回：

```json
{
  "result": "..."
}
```

工具调用结果在最终结果中以安全的文本或 JSON 摘要返回，不泄露内部命令、连接地址、认证信息和完整敏感参数。

请求失败时沿用现有 HTTP 400、401、404 语义；工具级失败保留稳定错误码，由 Agent 结果层明确说明“查询失败”或“结果未知”，不得编造业务结论。

`/api/tools` 继续只返回安全工具元数据；不新增未经鉴权的工具调用接口。

### 4.5 MCP 插件配置

保留现有插件清单格式。能耗系统接入时只需要提供插件目录和 `plugin.yaml`，例如：

```yaml
api_version: minimal-agent/v1
id: park-energy
version: 1.0.0
enabled: true
required: true
skills: []
mcp_servers:
  - id: energy
    transport: streamable_http
    url_env: PARK_ENERGY_MCP_URL
    headers_env:
      Authorization: PARK_ENERGY_MCP_TOKEN
    allowed_tools:
      - name: energy.query_trend
        side_effects: false
        idempotent: true
        timeout_seconds: 10
        result_size_limit: 262144
```

实际能耗 MCP Server 必须自行执行最终的园区、楼栋、租户权限校验。当前框架负责用户身份、任务归属、调用审计和能力边界，不假定 MCP Server 的业务权限模型。

### 4.6 功能开关与兼容性

结构化工具调用使用独立配置开关，默认关闭，便于灰度验证。开关关闭时：

- 旧 `/api/handle` 行为保持不变；
- 插件/MCP 仍可按现有配置加载，但不进入 Planner 的工具目录；
- 现有 275 个通过测试必须继续通过。

开启后若工具目录加载失败，遵循现有 required/optional 插件语义：必需插件阻止启动，可选插件记录稳定错误并保持 API 可用。

## 5. 错误与安全边界

- 未知工具：`unknown_tool`。
- Schema 不合法：`invalid_tool_arguments`。
- 执行超时：按工具副作用和幂等性区分可重试错误与 `unknown_outcome`。
- 结果不可序列化：`tool_result_not_serializable`。
- 结果超过限制：`tool_result_too_large`。
- MCP 连接、发现和关闭错误：沿用现有 MCP 稳定错误码。
- 工具目录只读，不允许模型修改工具定义或 allowlist。
- 工具调用审计记录调用者、工具名、状态、错误码和耗时，不记录完整密钥、命令参数或 Skill 正文。

## 6. 测试设计

### 单元测试

- 结构化计划项的合法、非法和未知字段解析。
- JSON 解析失败时仍按旧文本计划回退。
- 工具目录排序和敏感字段排除。
- 文本步骤与工具调用步骤的顺序执行。
- 工具调用上下文正确传递。

### 集成测试

- fake MCP Server 工具发现并注册到 CapabilityRegistry。
- `/api/handle` 通过结构化计划调用 fake MCP 工具。
- Schema、超时、结果过大、未知结果和远端错误均返回稳定状态。
- MCP 生命周期关闭后工具被注销，重新启动不会重复注册。
- API Key 用户只能访问自身任务和工具调用结果。

### 回归与验证

- `python -m pytest -q`
- `python -m pip check`
- `docker compose config --quiet`
- Docker build
- 至少一条启用结构化工具调用的本地 HTTP smoke test。

真实能耗 MCP、真实 OpenAI/Gemini 网络调用和真实园区权限验收不属于本阶段本地测试范围，应作为后续集成验收单独记录。

## 7. 分阶段交付

### 阶段一：运行时闭环

完成内部计划项、工具目录注入、结构化执行桥接、API 异步调用和回归测试。

### 阶段二：MCP 插件模板

增加通用 MCP 插件示例、部署配置和安全配置说明；使用 fake MCP Server 完成端到端验证。

### 阶段三：智慧园区能耗接入

由能耗系统提供真实 MCP Server 和工具契约，补充园区权限映射、指标口径和业务问法验收，不修改 Runtime 核心边界。

## 8. 完成标准

- 默认配置下旧功能和测试不回归。
- 开启开关后，模型可以通过 `/api/handle` 调用已注册 MCP 工具。
- 所有工具调用都经过统一 Schema、超时、结果大小和错误状态处理。
- MCP 生命周期由应用 lifespan 管理，不产生重复连接或泄漏。
- 工具调用不泄露密钥、命令、内部地址和 Skill 正文。
- 能耗系统只需提供符合契约的 MCP Server 和插件清单即可进行下一阶段接入。
