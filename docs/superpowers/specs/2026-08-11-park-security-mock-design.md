# 园区安防 Mock MCP 插件设计

## 目标与范围

为 Minimal Agent 增加与 `park_energy` 并列的 `park_security` 插件，以本地、确定性的 Mock 数据演示园区安防告警的统一研判和处置闭环。

一期覆盖视频、门禁、消防与巡更产生的结构化告警；不会接入真实设备协议、原始视频流、人脸库或外部工单系统。现有业务系统仍是数据权威来源；安防服务只消费其授权范围内的结构化事件，并生成归并事件和处置建议。

## 架构与边界

```text
Agent API / Planner / CapabilityRegistry
    -> park-security MCP（Streamable HTTP）
        -> SecurityService（查询与状态变更）
            -> EventCorrelator（告警归并与时间线）
            -> RiskAssessor（风险、影响范围与处置建议）
            -> MockSecurityRepository（确定性种子数据与内存状态）
```

- 主 Agent 沿用既有插件加载、MCP 工具发现、JSON Schema 校验、超时、结果限制和审计能力；不修改通用执行链路。
- `park_security` MCP 服务拥有全部安防领域规则与 Mock 数据。将来接入真实平台时，只替换数据适配层，不改变 MCP 工具契约。
- 返回的数据只包含结构化事件、设备状态和截图摘要引用；不返回原始视频、人员生物特征或凭据。
- 真实生产接入时，安防服务必须独立执行园区/区域/角色授权校验；主 Agent 的 API Key 鉴权不能替代领域授权。

## 领域模型

### SecurityAlarm

上游系统产生的原始告警。字段包括 `alarm_id`、`source`（video/access_control/fire/patrol）、`park_id`、`building_id`、`area_id`、`device_id`、`occurred_at`、`alarm_type`、`severity` 和结构化 `payload`。

### SecurityEvent

由多个原始告警归并形成的事件卡片。字段包括 `event_id`、园区与空间信息、`scenario`、`risk_level`、`status`、`first_occurred_at`、`last_occurred_at`、`alarm_ids`、`impact_scope`、`recommended_plan`、`responsible_party`、`evidence_completeness`、确认/关闭记录与工单标识。

### EvidenceItem、WorkOrder 与 AuditRecord

- `EvidenceItem`：事件时间线中的告警、授权通行、值班、预约、设备状态或截图摘要引用。
- `WorkOrder`：Mock 工单，含 `work_order_id`、关联事件、状态、责任人、创建与关闭时间。
- `AuditRecord`：人工确认、建单、关闭时记录操作人、时间、动作与备注。

## 归并和风险规则

Mock 数据固定为三种场景；归并规则以相同园区、相同或相邻重点区域、预设时间窗口和人员/设备关联为准：

1. **夜间异常通行**：非值班时段有人进入重点区域，关联门禁通行、值班表、预约缺失和视频摘要；风险等级为高。
2. **门禁异常与区域滞留**：短时间连续刷卡失败、重点区域停留和巡更缺失归并为一个事件；风险等级为中，若再次触发失败门禁事件则提升为高。
3. **消防与设备告警联动**：同一空间内烟感、温度和设备状态异常同时出现，形成时间线；风险等级为严重并推荐消防应急预案。

`RiskAssessor` 输出风险等级（`low`、`medium`、`high`、`critical`）、影响范围、责任方和推荐预案。它采用显式规则，避免示例中由模型直接决定风险或触发写操作。

## MCP 工具契约

| 工具 | 输入摘要 | 输出 | 副作用 |
| --- | --- | --- | --- |
| `security.get_event_summary` | `park_id` | 事件数量、按等级/状态统计、有效告警率等 | 无 |
| `security.list_events` | `park_id`、可选时间/等级/状态筛选 | 事件卡片列表 | 无 |
| `security.get_event_detail` | `event_id` | 时间线、证据、影响范围、预案和审计记录 | 无 |
| `security.get_shift_context` | `park_id`、可选 `area_id`、`at_time` | 重点区域、当班人员、责任区域和升级规则 | 无 |
| `security.confirm_event` | `event_id`、`operator_id`、备注 | 更新后的事件和审计记录 | 有 |
| `security.create_work_order` | `event_id`、`operator_id`、责任人 | 新建 Mock 工单和事件更新 | 有 |
| `security.close_event` | `event_id`、`operator_id`、处置说明 | 已关闭事件、复盘摘要和审计记录 | 有 |

所有工具响应使用稳定信封：`{ "success": true, "data": ..., "raw": ... }`。读取工具应为幂等；状态更新工具标记为有副作用且非幂等。错误响应使用已有 MCP 运行时规范化路径。

## 状态与处置流程

```text
open -> confirmed -> work_order_created -> closed
```

- `confirm_event` 仅允许从 `open` 转为 `confirmed`。
- `create_work_order` 仅允许已确认且尚未建单的事件，创建工单后转为 `work_order_created`。
- `close_event` 允许从 `confirmed` 或 `work_order_created` 转为 `closed`，并生成包含处置结果、时间线和证据完整度的简版复盘。
- 每次状态变更均要求非空 `operator_id`，写入 `AuditRecord`。不允许模型自主调用写工具；调用方须先人工确认。

## 插件与部署

新增目录 `plugins/park_security/`，结构与 `plugins/park_energy/` 一致：`plugin.yaml`、`README.md`、`server/config.py`、`server/models.py`、`server/mock_repository.py`、`server/service.py` 与 `server/main.py`。

`plugin.yaml` 声明一个 Streamable HTTP MCP 服务及上述七个 allowlisted 工具。Compose 增加 `park_security` 服务，开发环境默认 `PARK_SECURITY_DATA_MODE=mock`，Agent 通过 `PARK_SECURITY_MCP_URL` 和可选 `PARK_SECURITY_MCP_TOKEN` 连接。文档补充本地启动和环境变量说明。

## 测试与验收

- 模型测试：请求字段、风险枚举、状态机与响应信封。
- 服务测试：三个场景的归并结果、风险等级、时间线/证据、筛选和汇总指标。
- 写操作测试：无效状态转换拒绝，审计字段完整，工单不重复创建，关闭后复盘可查。
- 插件测试：清单可被当前 `PluginLoader` 正常读取，工具声明与名称一致。
- 回归：运行现有测试套件，确保能耗插件和主 Agent 不受影响。

验收时，用户能用自然语言或直接 MCP 工具查询三类事件，看到归并后的事件卡片、风险、证据链与推荐预案；人工确认后可创建和关闭 Mock 工单，并得到包含操作审计的简版复盘。
