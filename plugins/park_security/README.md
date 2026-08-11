# park-security 插件

`park-security` 是面向园区安防事件的 Streamable HTTP MCP mock 服务。它用确定性的内存数据演示告警关联、人工处置、工单和审计流程，不依赖真实安防平台。

## Mock 场景

- 夜间实验区异常门禁：非工作时间门禁拒绝与人员检测关联。
- 园区入口访问失败与徘徊：连续凭证失败、巡更上报和视频检测关联。
- 机房消防与设备故障：烟感、温升和通风设备故障关联为高优先级事件。

设置 `PARK_SECURITY_DATA_MODE=mock`（默认且当前唯一支持的模式）即可使用这些可重复的数据。

## 本地运行

在仓库根目录执行：

```powershell
$env:PARK_SECURITY_DATA_MODE = "mock"
$env:PARK_SECURITY_MCP_HOST = "127.0.0.1"
$env:PARK_SECURITY_MCP_PORT = "8200"
$env:PARK_SECURITY_APPROVAL_TOKEN = "<由人工审批系统签发的非空凭证>"
python -m plugins.park_security.server.main
```

MCP 端点为 `http://127.0.0.1:8200/mcp`。Compose 会将该端点发布到宿主机，并让 agent 在容器网络中使用 `http://park_security:8200/mcp`。

## 工具

- `security.get_event_summary`：按园区获取事件风险摘要。
- `security.list_events`：按时间、风险等级或状态筛选事件。
- `security.get_event_detail`：读取关联证据、处置状态和审计记录。
- `security.get_shift_context`：按园区、区域和可选 `at_time` 读取值班、区域和升级规则上下文；未知园区或区域会被拒绝。
- `security.confirm_event`：由具名操作员人工确认事件。
- `security.create_work_order`：为已确认事件创建工单。
- `security.close_event`：由具名操作员关闭已处置事件。

后三个工具具有副作用，且都要求显式传入非空 `approval_token`。服务只接受与
`PARK_SECURITY_APPROVAL_TOKEN` 完全匹配的凭证；未配置服务端凭证或凭证不匹配时，
写操作会被拒绝，前四个只读工具不受影响。`close_event` 还必须提供非空处置说明
`note`。

审批凭证必须由可信的人工审批客户端在确认操作后附加，不得注入 Planner、用户提示词
或 agent 容器环境。Compose 只把 `PARK_SECURITY_APPROVAL_TOKEN` 传给
`park_security` 服务。调用方还必须完成身份、园区和权限校验，并在未知执行结果时人工
核查，不能自动重放。

## 数据边界

该 mock 不处理原始视频、人体或人脸数据，也不连接真实工单系统。返回的证据引用和工单均是演示数据；生产接入必须由上游安防与工单系统负责租户隔离、授权、保留策略和敏感数据治理。
