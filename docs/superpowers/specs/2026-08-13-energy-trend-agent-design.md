# 能耗趋势 Agent 设计

## 目标

交付一个只读的端到端闭环：用户通过 minimal-agent 询问指定日期范围内的能耗趋势，Agent 调用 `cent-energy` 的 Agent 专用接口，基于 `cent_agent` 数据库中的真实电表累计读数返回日趋势、累计能耗、峰值、低谷和数据质量信息。

## 范围

本期仅实现按天能耗趋势查询，时间跨度最大 31 天。支持默认全部电表和按电表 ID 过滤。`projectIds` 作为未来网关权限上下文字段保留，但由于当前数据源没有项目映射，本期不使用它过滤数据。

不包含网关路由、登录态联调、项目/租户数据权限、区域排名、同比环比、异常归因、工单和设备控制。

## 架构与边界

```text
用户请求
  -> minimal-agent / park_energy.query_trend
  -> POST cent-energy /api/agent/v1/energy/trend
  -> cent_agent.device + cent_agent.device_data
  -> 统一趋势结果
  -> Agent 自然语言回答或图表数据
```

`cent-energy` 是数据口径和计算边界：读取电表、取读数、计算耗电量、处理无效数据，并返回结构化结果。`minimal-agent` 只负责将工具参数转换为 HTTP 请求、处理远端错误、将结果交给编排层；不连接业务数据库，也不计算电表读数。

`cent-energy` 现有默认数据源继续连接 `cent_energy`，保持后台管理功能不变。新增独立、只读的 `agent.datasource` 连接 `cent_agent`，仅由 Agent 能耗查询仓储使用；不得把默认 `spring.datasource` 切换到 `cent_agent`，也不得将数据库密码写入源码或提交到仓库。

## Java 接口

接口：`POST /api/agent/v1/energy/trend`

请求体：

```json
{
  "startDate": "2026-08-04",
  "endDate": "2026-08-10",
  "meterIds": [],
  "projectIds": []
}
```

校验规则：

- `startDate` 与 `endDate` 必填，格式为 `yyyy-MM-dd`；
- 开始日期不得晚于结束日期；
- 日期范围（含首尾）不得超过 31 天；
- `meterIds` 为空时查询全部电表；
- `projectIds` 仅保留在接口契约中，当前版本不参与过滤。

响应体：

```json
{
  "metric": "electricity",
  "unit": "kWh",
  "startDate": "2026-08-04",
  "endDate": "2026-08-10",
  "total": 12560.8,
  "averageDaily": 1794.4,
  "peak": { "date": "2026-08-08", "value": 2136.2 },
  "valley": { "date": "2026-08-03", "value": 1425.6 },
  "series": [
    { "date": "2026-08-04", "value": 1720.5, "meterCount": 4, "invalidMeterCount": 0 }
  ],
  "dataQuality": { "invalidReadingCount": 1, "missingMeterDayCount": 0 }
}
```

代码放在 `com.xhwl.energy.agent` 下，使用 Controller、Service、Dao、DTO 和 MyBatis XML 的现有分层习惯。新接口不修改现有后台管理 Controller。

## 数据口径

数据源为 `cent_agent.device` 和 `cent_agent.device_data`。`device_data.device_id` 与 `device.iot_device_id` 对应；`read_num` 是累计读数。

对每个“电表 + 自然日”，查询当天最早和最晚的有效读数：

```text
日能耗 = 最晚 read_num - 最早 read_num
```

- 差值大于或等于 0：纳入当天电表能耗；
- 差值小于 0：视为读数回退，不计入能耗，`invalidReadingCount` 加一；
- 当天不足两条读数：不生成该电表当天能耗，`missingMeterDayCount` 加一；
- 每日总能耗为当天所有有效电表能耗之和；
- `meterCount` 为当天参与汇总的有效电表数；
- 若整个日期范围没有有效日电量，返回空 `series`、`total=0`，峰值和低谷为 `null`。

## minimal-agent 接入

保留 `plugins/park_energy` 的工具名称和 Mock 模式。为 REST 模式添加配置：

```text
PARK_ENERGY_MODE=rest
PARK_ENERGY_BASE_URL=http://cent-energy:9714
PARK_ENERGY_TIMEOUT_SECONDS=10
```

`query_trend` 将对话层的 `start_date`、`end_date` 和可选范围参数转换为 Java 请求体，并将 Java 返回的统一结构作为工具结果。非 2xx 响应、超时和格式不合法响应必须转为明确的工具错误；不得回退为伪造 Mock 数据。

## 安全与后续演进

接口只读。本期开发环境可通过内网访问，但上线前必须由 Gateway 注入并签名用户、应用、项目范围和追踪 ID；`cent-energy` 必须用项目范围二次过滤。Python 服务不得持有用户 JWT 签名密钥，也不得直接暴露数据库凭据。

## 验收与测试

Java 侧：验证正常读数、读数回退、读数不足、日期范围非法、多电表汇总及无有效数据。Python 侧：验证 REST 请求映射、成功响应解析、远端错误、超时和保留 Mock 行为。

验收问题：`近 7 天能耗趋势怎么样？`。系统应返回真实累计能耗、逐日序列、峰值、低谷和数据质量统计；输出口径能够与同一 SQL 计算结果核对。
