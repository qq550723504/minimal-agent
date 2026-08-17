# 能耗 Agent 展示设计

## 目标

在现有园区安防 Agent 页面中增加能耗查询展示能力。用户继续通过自然语言提问，Agent 通过已注册的 `park-energy` MCP 调用 `cent-energy` Java 接口，页面将能耗结果渲染为可读卡片。

## 范围

- 复用现有 `POST /api/handle` 与 `response_mode=structured` 协议。
- 支持 `energy.query_trend`、`energy.query_ranking`、`energy.get_peak_value`、`energy.compare_period`、`energy.get_alarm_summary` 五类只读工具。
- 保留原有文本模式和安防结构化卡片，不改变数据库访问边界。
- 能耗 MCP 通过环境变量配置；Agent 不直连 `cent_energy` 数据库。

## 页面行为

同一个聊天窗口接受“查询最近 7 天能耗”“哪栋楼能耗最高”等问题。返回内容包括 Agent 自然语言摘要和能耗卡片：趋势卡片显示时间序列及累计值，排名卡片显示楼宇/电表排名，峰值卡片显示峰值与时间，对比卡片显示当前值、基准值和变化率，异常卡片显示异常读数及影响范围。

未识别的工具结果仍以通用 JSON 展示；接口错误显示错误状态，不伪造能耗数据。

## 数据流与配置

```text
browser -> minimal-agent /api/handle
        -> park-energy MCP
        -> cent-energy /api/agent/v1/energy/*
        -> cent_energy
```

生产模式使用 `PARK_ENERGY_DATA_MODE=rest`、`ENERGY_API_BASE_URL` 和受控的 `ENERGY_PROJECT_IDS`。没有 Java 服务时可使用 park-energy mock，但页面必须明确这是演示数据。

## 验收标准

1. 结构化响应能将五个能耗工具解码为稳定的 block type。
2. 页面能为每类能耗 block 渲染对应卡片，并安全处理缺失字段和错误结果。
3. 安防 block、文本接口和现有 MCP 能力测试全部保持通过。
4. 能耗 MCP 配置和访问地址写入插件 README。
