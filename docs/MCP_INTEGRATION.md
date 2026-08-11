# MCP 与园区能耗和安防接入指南

本文说明如何把已经提供 MCP Server 的园区能耗或安防系统接入 Minimal Agent。框架负责插件加载、工具发现、参数校验、超时、结果大小、审计和用户任务归属；远端 MCP Server 仍必须负责园区、楼栋、租户和数据权限校验。

## 一、能力边界

结构化工具调用目前有两条开关边界：

| 场景 | 必需配置 |
| --- | --- |
| 内置本地工具的结构化调用 | `AGENT_STRUCTURED_TOOL_CALLING_ENABLED=true` |
| 插件 Skill / MCP 工具 | 上述开关 + `AGENT_CAPABILITY_RUNTIME_ENABLED=true` |
| Streamable HTTP MCP | 另外配置 `AGENT_MCP_ALLOWED_HOSTS`；开发模式可显式允许本机 HTTP，生产模式必须使用 HTTPS |
| stdio MCP | 另外配置 `AGENT_MCP_STDIO_ALLOWED_COMMANDS` 精确可执行文件路径 |

两个结构化开关默认都是 `false`。配置在服务启动时读取，修改后需要重启服务。当前只有同步 `/api/handle` 支持结构化 MCP 工具调用；`/api/handle/queue` 仍使用旧版字符串步骤语义。

## 二、园区能耗 MCP 插件

### 2.1 Streamable HTTP 示例

目录结构：

```text
plugins/
└── park-energy/
    └── plugin.yaml
```

`plugins/park-energy/plugin.yaml`：

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
      - name: energy.get_alarm_summary
        side_effects: false
        idempotent: true
        timeout_seconds: 10
        result_size_limit: 262144
```

启动服务前提供实际值，不要把 URL、Token 或其他密钥写入 `plugin.yaml`：

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "energy.example.com"
$env:PARK_ENERGY_MCP_URL = "https://energy.example.com/mcp"
$env:PARK_ENERGY_MCP_TOKEN = "<secret>"
```

`url_env` 的值是环境变量名；`headers_env` 的键是发送给 MCP Server 的 HTTP Header，值是环境变量名。开发模式只允许 `AGENT_MCP_ALLOWED_HOSTS` 中明确列出的本机 HTTP 目标，适合本地 mock 服务；生产模式仍必须使用 HTTPS，并启用 API Key 鉴权及 `docker-compose.production.yml` 中要求的生产配置。上述配置在服务启动时读取，修改后需要重启 agent。

本地宿主机运行 `park_energy` 时可以使用：

```powershell
$env:AGENT_DEPLOYMENT_MODE = "development"
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "127.0.0.1"
$env:PARK_ENERGY_MCP_URL = "http://127.0.0.1:8100/mcp"
$env:PARK_ENERGY_MCP_TOKEN = ""
```

使用 Docker Compose 时，agent 容器应通过服务名连接 park-energy：将
`PARK_ENERGY_MCP_URL` 设为 `http://park_energy:8100/mcp`，并将
`AGENT_MCP_ALLOWED_HOSTS` 设为 `park_energy`。

### 2.2 stdio 示例

stdio MCP 等同于管理员授予服务启动本地程序的权限，必须使用精确的可执行文件 allowlist：

```yaml
api_version: minimal-agent/v1
id: park-energy-local
version: 1.0.0
enabled: true
required: false
skills: []
mcp_servers:
  - id: energy
    transport: stdio
    command: /opt/park-energy/bin/energy-mcp
    args: []
    cwd: .
    env_vars:
      PARK_ENERGY_TOKEN: PARK_ENERGY_TOKEN
    allowed_tools:
      - name: energy.query_trend
        side_effects: false
        idempotent: true
        timeout_seconds: 10
        result_size_limit: 262144
```

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_STDIO_ALLOWED_COMMANDS = "/opt/park-energy/bin/energy-mcp"
$env:PARK_ENERGY_TOKEN = "<secret>"
```

`command` 必须与解析后的实际可执行文件路径精确匹配，`cwd` 必须位于插件目录内；shell、`.cmd` 和 `.bat` 包装器不会被接受。`env_vars` 只允许把已存在的宿主环境变量映射给子进程。

### 2.3 园区安防 mock 示例

`plugins/park_security/plugin.yaml` 使用 `PARK_SECURITY_MCP_URL` 和
`PARK_SECURITY_MCP_TOKEN` 注入连接信息。Compose 默认在 agent 容器内将 URL
设为 `http://park_security:8200/mcp`；因此使用 Compose 时，允许的 MCP 主机名
应包含 `park_security`：

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "park_security"
$env:PARK_SECURITY_MCP_URL = "http://park_security:8200/mcp"
$env:PARK_SECURITY_MCP_TOKEN = ""
$env:PARK_SECURITY_DATA_MODE = "mock"
$env:PARK_SECURITY_APPROVAL_TOKEN = "<由人工审批系统签发的非空凭证>"
docker compose up --build
```

直接在宿主机运行时，把 URL 和 allowlist 改为 `127.0.0.1`：

```powershell
$env:AGENT_DEPLOYMENT_MODE = "development"
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "127.0.0.1"
$env:PARK_SECURITY_MCP_URL = "http://127.0.0.1:8200/mcp"
$env:PARK_SECURITY_MCP_TOKEN = ""
$env:PARK_SECURITY_DATA_MODE = "mock"
$env:PARK_SECURITY_APPROVAL_TOKEN = "<由人工审批系统签发的非空凭证>"
```

安防 mock 提供夜间异常门禁、入口访问失败与徘徊、消防与设备故障三种关联告警场景，以及七个工具：
`security.get_event_summary`、`security.list_events`、`security.get_event_detail`、
`security.get_shift_context`、`security.confirm_event`、`security.create_work_order` 和
`security.close_event`。前四个工具只读；后三个工具有副作用且非幂等，必须由调用方
进行人工确认、权限校验和未知结果核查。三个写工具均要求人工审批客户端显式提供
`approval_token`；园区安防服务使用 `PARK_SECURITY_APPROVAL_TOKEN` 做恒定时间比较，
未配置或不匹配时拒绝写入。该服务端凭证不得进入 Planner、用户提示词或 agent 环境，
Compose 也只将其传给 `park_security` 服务。`close_event` 还要求非空 `note` 作为处置
说明；关闭关联事件时，Mock 工单会同步写为 `closed` 并记录固定关闭时间。

生产系统不应把原始视频、人脸或真实工单数据送入该 mock。实际安防 MCP Server 必须
自行处理敏感数据最小化、园区/租户隔离、授权和工单系统的幂等控制。

## 三、工具命名与调用流程

MCP 工具必须同时满足以下条件才会注册：

1. MCP Server 能成功连接并完成工具发现。
2. 工具名称出现在 `allowed_tools` 中。
3. `side_effects` 和 `idempotent` 被明确声明。
4. MCP 返回的输入 Schema 能通过框架校验。

服务会通过 `/api/tools` 返回实际注册的安全元数据。MCP 工具名会加入插件和 Server 命名空间；远端工具名含点号或其他非简单字符时会编码成 `mcp-encoded-*` 片段。不要在业务代码中猜测名称，应以 `/api/tools` 返回值为准。

调用链如下：

```text
自然语言请求
  -> Planner 生成字符串步骤或 ToolCallPlan
  -> CapabilityRegistry 校验工具名、JSON Schema 和 timeout
  -> 本地处理器或 MCP Server
  -> ToolResult
  -> /api/handle 返回 result
```

结构化工具调用对象格式：

```json
{
  "kind": "tool_call",
  "call_id": "call-1",
  "tool": "<GET /api/tools 返回的名称>",
  "arguments": {
    "park_id": "park-a",
    "building_id": "building-1",
    "date": "2026-08-09"
  }
}
```

请求示例：

```bash
curl -X POST http://localhost:8000/api/handle \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <api-key>" \
  -d '{"prompt":"查询园区 park-a 的 building-1 昨日用电趋势，并说明异常峰值"}'
```

响应仍是同步接口原有格式：

```json
{"result":"..."}
```

安防事件查询可使用同一路径；以下 prompt 让规划器调用已注册的只读安防工具：

```bash
curl -X POST http://localhost:8000/api/handle \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <api-key>" \
  -d '{"prompt":"查询 park-1 的高风险安防事件，并给出夜班值守与升级建议"}'
```

当前没有公开的直接工具调用 API。规划器可以在同一计划中混合文本步骤和工具调用，工具按计划顺序串行执行；无法通过结构化校验的模型输出会降级为文本，不会把任意 JSON 对象直接执行。

## 四、接入验证

### 4.1 配置检查

```bash
docker compose config --quiet
```

检查服务启动日志，确认必需插件没有被禁用。`required: true` 的插件连接、发现或 allowlist 配置失败会阻止服务启动；`required: false` 的插件会记录稳定错误并保持主服务可用。

### 4.2 目录检查

鉴权开启时为每个请求添加 `X-API-Key`：

```bash
curl -H "X-API-Key: <api-key>" http://localhost:8000/api/plugins
curl -H "X-API-Key: <api-key>" http://localhost:8000/api/tools
curl -H "X-API-Key: <api-key>" http://localhost:8000/api/skills
```

确认：

- `/api/plugins` 中 `park-energy` 状态为可用。
- `/api/tools` 中出现能耗 MCP 工具及其 `input_schema`、`side_effects`、`idempotent` 元数据。
- 响应中没有 URL、命令、环境变量值、Token 或 Skill 正文。

### 4.3 业务验证

至少验证以下只读场景：

- 日/小时用电趋势查询。
- 楼栋或设备能耗排名。
- 峰值、越限和异常告警摘要。
- 统计口径、时间范围和单位的解释。

验证写操作前，先把对应工具声明为 `side_effects: true`，确认 MCP Server 的幂等键、权限校验和未知结果处理已经设计完成。框架不会替远端 MCP Server 推断业务权限。

## 五、故障定位

### 5.1 本地开发常见坑

本地联调时需要区分 Docker Compose 和直接运行 Python：

- 两个 capability 开关默认都是 `false`。修改 `.env` 或环境变量后必须重启 agent；已经运行的进程不会重新读取配置。
- Docker Compose 会自动读取项目根目录的 `.env`。直接执行 `python -m plugins.park_energy.server.main` 或 `python -m uvicorn ...` 不会自动读取 `.env`，必须在同一个 PowerShell 会话中显式设置环境变量，或使用 Compose 启动。
- 宿主机直接运行时使用 `PARK_ENERGY_MCP_URL=http://127.0.0.1:8100/mcp` 和 `AGENT_MCP_ALLOWED_HOSTS=127.0.0.1`；Compose 内的 agent 必须使用 `http://park_energy:8100/mcp` 和 `AGENT_MCP_ALLOWED_HOSTS=park_energy`，容器内的 `127.0.0.1` 指向 agent 自身。
- `PARK_ENERGY_DATA_MODE=mock` 只对实际启动的 `park_energy` 进程生效。若直接运行 Python 时没有传入该变量，服务会回退到 `rest`，随后可能出现 `mcp_tool_error`，实际根因是上游 REST API 不可用或返回了非 JSON。
- Gemini 结构化调用依赖 JSON 响应约束和工具输入 Schema。只提供自然语言提示时，模型可能只输出“调用某接口”的文字；这不等于工具已经执行。`/api/handle` 的请求应包含 `park_id`、时间范围等工具必填参数，缺少 `park_id` 时要求补充是正常行为。
- 审计日志中的 `[REDACTED]` 是脱敏标记，不代表时间或业务数据被 MCP 修改。`mcp_tool_error` 表示 MCP Server 返回了错误结果；应同时检查 MCP 服务自身日志和 `PARK_ENERGY_DATA_MODE`，不要只看 agent 的脱敏错误码。

宿主机直接运行 mock 服务的最小配置：

```powershell
$env:PARK_ENERGY_DATA_MODE = "mock"
$env:PARK_ENERGY_MCP_HOST = "127.0.0.1"
$env:PARK_ENERGY_MCP_PORT = "8100"
python -m plugins.park_energy.server.main
```

验证工具注册和调用时，先检查 `/api/plugins`、`/api/tools`，再使用明确的业务请求，例如：

```text
查询园区 park-2 今天的电耗数据，按天统计
```

| 现象或错误码 | 含义 | 处理方向 |
| --- | --- | --- |
| `unknown_tool` | 规划器生成了未注册工具 | 以 `/api/tools` 返回名为准，检查插件是否成功加载 |
| `invalid_tool_arguments` | 参数不符合 MCP 工具 JSON Schema | 检查字段、类型、必填项和时间格式 |
| `mcp_tool_error` | MCP Server 返回了 `is_error=true` | 检查 park_energy 是否误运行在 `rest` 模式、上游 API 是否可用，以及 MCP Server 自身日志 |
| `tool_timeout` | 本地能力执行超时 | 调整工具 timeout 或拆分查询范围 |
| `mcp_tool_transport_failed` | 幂等工具的 MCP 传输失败 | 检查 URL、网络、DNS 和 MCP Server 健康状态 |
| `mcp_tool_unknown_outcome` | 非幂等工具执行结果未知 | 不要自动重试，先到业务系统确认是否已生效 |
| `tool_result_too_large` | 结果超过工具或全局上限 | 缩小时间范围、分页或在 MCP Server 侧聚合 |
| `declared_tool_missing` | `allowed_tools` 中声明的工具未被 MCP 发现 | 检查工具名称和 MCP Server 版本 |
| `mcp_startup_timeout` / `mcp_tool_discovery_timeout` | 连接或工具发现超时 | 检查服务启动依赖和三个 MCP 生命周期 timeout 配置 |

Prometheus 指标通过 `/metrics` 暴露；开启 metrics 鉴权时使用：

```bash
curl -H "Authorization: Bearer <metrics-api-key>" http://localhost:8000/metrics
```

工具参数、工具结果、Token、命令和用户敏感信息不会作为指标标签输出。审计日志应结合用户、工具名、状态和错误码定位问题，不要把密钥写入 Prompt 或插件清单。

## 六、生产检查清单

- [ ] `AGENT_DEPLOYMENT_MODE=production`。
- [ ] `AGENT_AUTH_REQUIRED=true`，并配置非 default 的 `AGENT_API_KEYS`。
- [ ] `AGENT_METRICS_API_KEY` 已替换为随机非默认值。
- [ ] `AGENT_MCP_ALLOWED_HOSTS` 或 `AGENT_MCP_STDIO_ALLOWED_COMMANDS` 只包含明确批准的目标。
- [ ] HTTP MCP 使用 HTTPS；远端 MCP Server 自行执行园区、楼栋、租户和用户权限校验。
- [ ] 插件目录只读挂载，Token 通过环境变量或密钥管理系统注入。
- [ ] 只读工具先完成业务验收，再开放有副作用工具。
- [ ] 对 `unknown_outcome` 建立人工确认流程，不自动重放非幂等写操作。
- [ ] 使用队列功能时保持单实例；多副本前迁移到外部队列和共享数据库。
