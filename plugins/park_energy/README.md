# park-energy 插件

`park-energy` 是一个轻量级 MCP 服务端，通过封装 REST 接口或确定性的本地
mock 数据，对外提供园区能耗相关工具。

## 环境变量

```powershell
$env:PARK_ENERGY_DATA_MODE = "rest"
$env:ENERGY_API_BASE_URL = "https://energy.example.com"
$env:ENERGY_API_TOKEN = "<secret>"
$env:ENERGY_API_TOKEN_HEADER = "Authorization"
$env:ENERGY_API_TOKEN_PREFIX = "Bearer"
$env:ENERGY_API_TIMEOUT_SECONDS = "10"
$env:ENERGY_TREND_PATH = "/api/agent/v1/energy/trend"
$env:ENERGY_PROJECT_IDS = "101,102"
$env:ENERGY_RANKING_PATH = "/api/energy/ranking"
$env:ENERGY_PEAK_PATH = "/api/energy/peak"
$env:ENERGY_COMPARE_PATH = "/api/energy/compare"
$env:ENERGY_ALARMS_PATH = "/api/energy/alarms"
$env:PARK_ENERGY_MCP_HOST = "127.0.0.1"
$env:PARK_ENERGY_MCP_PORT = "8100"
$env:ENERGY_API_MAX_RESPONSE_BYTES = "1048576"
```

- 如果你的后端路由路径不同，请覆盖 `ENERGY_*_PATH` 相关变量。
- 如果接口是公开的，`ENERGY_API_TOKEN` 可选。
- `ENERGY_PROJECT_IDS` 是服务端受控的项目范围，趋势查询必须非空；不要从用户自然语言直接拼接该变量。

## 真实 Java 闭环联调

按以下顺序启动本地链路：

1. 启动 `cent-energy`，确认趋势接口监听 `http://127.0.0.1:19714`。
2. 设置 `PARK_ENERGY_DATA_MODE=rest`、`ENERGY_API_BASE_URL=http://127.0.0.1:19714`、`ENERGY_PROJECT_IDS=2709`。
3. 启动 park-energy MCP 服务。
4. 启动 Agent，并显式设置 `AGENT_CAPABILITY_RUNTIME_ENABLED=true`、`AGENT_STRUCTURED_TOOL_CALLING_ENABLED=true`、`AGENT_MCP_ALLOWED_HOSTS=127.0.0.1`。

用户请求“查询最近 7 天能耗”时，Agent 会调用 `energy.query_trend`，由 Java 查询 `cent_energy` 后返回趋势、累计值、峰值和数据质量。

与安防 Agent 页面合并展示时，同时设置：

```powershell
$env:PARK_SECURITY_MCP_URL = "http://127.0.0.1:8200/mcp"
$env:PARK_ENERGY_MCP_URL = "http://127.0.0.1:8100/mcp"
```

然后访问 <http://127.0.0.1:8000/security/>。页面会在同一个对话中展示安防卡片和能耗趋势、排名、峰值、周期对比及异常卡片；页面不连接 `cent_energy` 数据库。
- `PARK_ENERGY_DATA_MODE` 取值为 `rest` 或 `mock`，默认是 `rest`。
- `mock` 模式下，五个工具返回可重复的示例数据，不会请求上游 API。

## 本地运行

在仓库根目录执行：

```powershell
python -m plugins.park_energy.server.main
```

服务会监听 `PARK_ENERGY_MCP_HOST` 与 `PARK_ENERGY_MCP_PORT`。
默认监听本机地址，不会把未鉴权的 MCP 端点暴露到外网。若你将主机设置为
`0.0.0.0`，请将服务放在带有鉴权并受网络限制的网关之后。

没有真实能耗 API 时，可以使用 mock 数据：

```powershell
$env:PARK_ENERGY_DATA_MODE = "mock"
$env:PARK_ENERGY_MCP_HOST = "127.0.0.1"
$env:PARK_ENERGY_MCP_PORT = "8100"
python -m plugins.park_energy.server.main
```

mock 服务地址为 `http://127.0.0.1:8100/mcp`。

## 与 minimal-agent 一起使用 Compose

仓库的 Compose 配置会同时启动 `agent`、`park_energy` 和 Prometheus。
开发环境默认使用 mock 数据；如果宿主机 `8000` 已被占用，可以只调整
agent 的宿主机端口：

```powershell
$env:AGENT_HOST_PORT = "8001"
docker compose up --build
```

agent 地址为 `http://localhost:8001/`，park-energy 的直接 MCP 地址为
`http://127.0.0.1:8100/mcp`。两个服务会并行运行；开发模式下 minimal-agent
允许显式 allowlist 的本机 HTTP MCP，生产模式仍要求 HTTPS。

## MiniAgent 集成

对于 HTTPS MCP 服务：

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "energy.example.com"
$env:PARK_ENERGY_MCP_URL = "https://energy.example.com/mcp"
$env:PARK_ENERGY_MCP_TOKEN = "<secret>"
```

启动 MiniAgent 后访问 `/api/tools`，确认插件是否已注册。

本地 mock 接入 agent 时，先设置 `AGENT_DEPLOYMENT_MODE=development`、
`AGENT_MCP_ALLOWED_HOSTS=127.0.0.1`、`PARK_ENERGY_MCP_URL=http://127.0.0.1:8100/mcp`
和空的 `PARK_ENERGY_MCP_TOKEN`，同时开启两个 capability 开关，然后重启
MiniAgent。Docker Compose 内请使用 `park_energy` 作为 URL 主机名和 allowlist 值。

## 工具

- `energy.query_trend`
  - 必填参数：`park_id`、`start_time`、`end_time`
  - 可选参数：`building_id`、`energy_type`（默认 `electricity`）、`granularity`（默认 `day`）
  - REST 模式 POST 到 `/api/agent/v1/energy/trend`，日期映射为 `startDate`/`endDate`，项目范围来自 `ENERGY_PROJECT_IDS`。
- `energy.query_ranking`
  - REST 模式 POST 到 `/api/agent/v1/energy/ranking`，返回按电表降序的 `items`。
- `energy.get_peak_value`
- `energy.compare_period`
  - REST 模式 POST 到 `/api/agent/v1/energy/compare`，返回 `currentTotal`、`baselineTotal`、`delta`、`changePercent`。
- `energy.get_alarm_summary`
  - REST 模式 POST 到 `/api/agent/v1/energy/anomalies`，返回异常读数、缺失读数和受影响电表日数量。

## 插件信息

- 插件 ID：`park-energy`
- 通信方式：`streamable_http`
- 默认端口：`8100`

## Java 趋势接口手工联调

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:9714/api/agent/v1/energy/trend" `
  -ContentType "application/json" `
  -Body '{"startDate":"2026-08-04","endDate":"2026-08-10","meterIds":[],"projectIds":[101]}'
```
