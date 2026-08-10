# park-energy

面向 Minimal Agent 的只读能耗 MCP Server，用于将稳定的能耗工具调用转换为对现有园区能耗 REST API 的请求。

## 环境变量

```powershell
$env:ENERGY_API_BASE_URL = "https://energy.example.com"
$env:ENERGY_API_TOKEN = "<secret>"
$env:ENERGY_API_TOKEN_HEADER = "Authorization"
$env:ENERGY_API_TOKEN_PREFIX = "Bearer"
$env:ENERGY_API_TIMEOUT_SECONDS = "10"
$env:PARK_ENERGY_MCP_HOST = "0.0.0.0"
$env:PARK_ENERGY_MCP_PORT = "8100"
```

上游接口路径默认如下：

- `/api/energy/trend`：能耗趋势
- `/api/energy/ranking`：能耗排名
- `/api/energy/peak`：峰值查询
- `/api/energy/compare`：周期对比
- `/api/energy/alarms`：能耗告警

拿到真实接口文档后，可以通过 `ENERGY_*_PATH` 环境变量覆盖这些默认路径。

## 本地运行

在仓库根目录执行：

```powershell
python -m plugins.park_energy.server.main
```

插件 ID 保持为 `park-energy`，供 miniagent 发现和加载。

## 接入 miniagent

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "energy.example.com"
$env:PARK_ENERGY_MCP_URL = "https://energy.example.com/mcp"
$env:PARK_ENERGY_MCP_TOKEN = "<secret>"
```

miniagent 启动后，可以通过 `/api/tools` 查看实际注册的工具。业务代码应以该接口返回的工具名称为准，不要自行猜测工具名。

## 当前工具

当前只开放以下只读工具：

- `energy.query_trend`：查询园区或楼栋的能耗趋势
- `energy.query_ranking`：查询能耗排名
- `energy.get_peak_value`：查询能耗峰值
- `energy.compare_period`：对比两个时间周期的能耗
- `energy.get_alarm_summary`：查询能耗异常和告警摘要

## 下一步配置

接入真实能耗系统前，需要补充以下信息：

- 各工具对应的 REST 接口路径
- 请求参数名称和数据类型
- 认证方式
- 一份脱敏后的响应示例

拿到这些信息后，再完善 REST 响应的标准化映射，避免把上游接口的字段差异暴露给 Agent。
