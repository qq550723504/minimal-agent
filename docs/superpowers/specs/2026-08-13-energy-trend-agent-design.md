# 能耗趋势 Agent 设计

## 目标

交付一个只读闭环：用户通过 minimal-agent 查询指定日期范围的能耗趋势，Agent 调用 `cent-energy` 的专用接口，基于 `cent_energy` 库中现有的电表上报数据返回日趋势、累计能耗、峰值、低谷和数据质量。

## 范围

本期仅实现按天能耗趋势，时间跨度最大 31 天。支持按项目、电表筛选；`projectIds` 是后续 Gateway 权限上下文的承载字段，本期由请求传入并用于查询过滤。

不包含 Gateway 路由、真实登录态联调、区域排名、同比环比、异常归因、工单和设备控制。

## 架构与边界

```text
用户
  -> minimal-agent / park_energy.query_trend
  -> POST cent-energy /api/agent/v1/energy/trend
  -> cent_energy: CMC_DEVICE_REPORT_DATA / CMC_DEVICE_METER_INFO
  -> 统一趋势结果
  -> Agent 回答或图表
```

`cent-energy` 继续使用其默认 `spring.datasource` 连接 `cent_energy`，不增加第二数据源，也不访问 `cent_agent`。Java 负责查询、数据口径和数据范围过滤；minimal-agent 只负责工具参数转换、远端错误处理和结果编排，不直连数据库。

## Java 接口

接口：`POST /api/agent/v1/energy/trend`

```json
{
  "startDate": "2026-08-04",
  "endDate": "2026-08-10",
  "meterIds": [],
  "projectIds": [101]
}
```

规则：日期必填、开始不得晚于结束、含首尾不超过 31 天；`meterIds` 为空时查询授权项目内的全部电表；`projectIds` 为空时第一期返回参数错误，避免无范围查询。

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

新代码放在 `com.xhwl.energy.agent`，不修改既有管理 Controller。

## 数据口径

主数据来自 `CMC_DEVICE_METER_INFO`：通过 `DEVICE_CODE` 关联上报数据，使用其 `PROJECT_ID` 过滤项目范围。读数来自 `CMC_DEVICE_REPORT_DATA`：`ACTIVE_ENERGY` 为累计有功电能，`CREATED_DATE` 为采集时间，`DEVICE_CODE` 为电表标识。

对每个“电表 + 自然日”按 `CREATED_DATE` 找最早与最晚的 `ACTIVE_ENERGY`：

```text
日电量 = 最晚 ACTIVE_ENERGY - 最早 ACTIVE_ENERGY
```

- 差值大于等于零：纳入日电量；
- 差值小于零：视为读数回退，不计入并增加 `invalidReadingCount`；
- 当天不足两条有效读数：不计入并增加 `missingMeterDayCount`；
- 项目日电量为全部有效电表日电量之和；
- 若无有效日电量：返回空 `series`、零总量和空峰/谷。

## minimal-agent 接入

保留 `park_energy` 工具名与 Mock 模式。REST 模式配置使用：

```text
PARK_ENERGY_DATA_MODE=rest
ENERGY_API_BASE_URL=http://cent-energy:9714
ENERGY_TREND_PATH=/api/agent/v1/energy/trend
ENERGY_API_TIMEOUT_SECONDS=10
```

`query_trend` 将 `start_time` 和 `end_time` 映射为日期字段，并从后续的可信 Gateway 上下文提供 `projectIds`。本地联调时可由受控测试配置提供项目 ID；远端非 2xx、超时、失败 `ResultJson` 或非法 JSON 必须返回工具错误，不得回退为 Mock 数据。

## 安全与验收

接口只读。上线前 Gateway 必须注入可信 `userId`、`projectIds`、角色和追踪 ID；`cent-energy` 用项目范围二次过滤。Python 不持有用户 JWT 密钥或数据库凭据。

Java 测试覆盖正常读数、回退、缺失、日期非法、跨项目过滤、多电表汇总和空结果；Python 测试覆盖 POST 映射、成功与失败 ResultJson、超时及 Mock 兼容。

验收问题：`近 7 天能耗趋势怎么样？`。结果必须与同一 `cent_energy` 数据口径的 SQL 聚合结果一致。
