# 园区安防 Mock MCP 插件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个确定性本地 Mock 的园区安防 MCP 插件，支持告警归并事件查询、风险与证据摘要、人工确认、Mock 工单和闭环复盘。

**Architecture:** 主 Agent 保持现有插件加载和 MCP 工具注册链路不变。`plugins/park_security` 作为独立 Streamable HTTP MCP 服务，由 Pydantic 模型定义契约、内存仓储保存固定告警/事件和写状态、服务层执行查询及状态机，`main.py` 仅把显式 MCP 参数适配到服务方法。

**Tech Stack:** Python 3.11、Pydantic 2、MCP SDK 2.0、pytest、Docker Compose。

## Global Constraints

- 一期只使用确定性 Mock 结构化数据；不得连接真实视频、门禁、消防、巡更或工单平台。
- 不得返回原始视频、人脸库、生物特征或通行凭据；仅返回事件元数据和截图摘要引用。
- 所有响应必须沿用 `{ "success": true, "data": ..., "raw": ... }` 信封。
- 写操作必须要求非空 `operator_id`，更新内存状态并追加审计记录；不能由模型绕过人工确认直接触发。
- 读取工具标记为 `side_effects: false`、`idempotent: true`；写工具标记为 `side_effects: true`、`idempotent: false`。
- Agent 核心的 Planner、CapabilityRegistry、插件加载器和 MCP 适配器不作改动。

---

## File Structure

- Create: `plugins/park_security/__init__.py` — 安防插件 Python 包标记。
- Create: `plugins/park_security/plugin.yaml` — 插件与七个 MCP allowlist 工具声明。
- Create: `plugins/park_security/README.md` — 本地启动、工具、Mock 场景和安全边界说明。
- Create: `plugins/park_security/server/__init__.py` — MCP 服务包标记。
- Create: `plugins/park_security/server/config.py` — 安防 MCP 主机、端口和 Mock 模式配置。
- Create: `plugins/park_security/server/models.py` — 查询、状态变更、原始告警、事件、证据、工单、审计和响应信封模型。
- Create: `plugins/park_security/server/mock_repository.py` — 三类确定性场景及内存状态的隔离读写。
- Create: `plugins/park_security/server/service.py` — 事件筛选、汇总、风险/处置上下文、状态机和复盘逻辑。
- Create: `plugins/park_security/server/main.py` — 使用显式入参注册的七个 MCP 工具。
- Create: `tests/infrastructure/plugins/test_park_security.py` — 配置、Mock 数据、服务状态机和 MCP 处理器测试。
- Modify: `docker-compose.yml` — 增加 `park_security` 服务、Agent 连接变量和健康依赖。
- Modify: `README.md` — 说明安防插件本地 Compose 运行与环境变量。
- Modify: `docs/MCP_INTEGRATION.md` — 增加园区安防 Mock 接入示例。

### Task 1: 安防领域模型和配置

**Files:**
- Create: `plugins/park_security/__init__.py`
- Create: `plugins/park_security/server/__init__.py`
- Create: `plugins/park_security/server/config.py`
- Create: `plugins/park_security/server/models.py`
- Test: `tests/infrastructure/plugins/test_park_security.py`

**Interfaces:**
- Produces: `Settings.from_env() -> Settings`，其中 `host: str`、`port: int`、`data_mode: Literal["mock"]`。
- Produces: `SecurityAlarm`、`EvidenceItem`、`AuditRecord`、`WorkOrder`、`SecurityEvent` Pydantic 模型；`EventStatus = Literal["open", "confirmed", "work_order_created", "closed"]` 和 `RiskLevel = Literal["low", "medium", "high", "critical"]`。
- Produces: `EventListQuery(park_id, start_time=None, end_time=None, risk_level=None, status=None)`、`EventAction(event_id, operator_id, note=None)`、`CreateWorkOrder(event_id, operator_id, assignee, note=None)` 和 `wrap_response(payload)`。
- Consumed later: 仓储和服务层只使用这些模型，不接受未校验的字典作为公共入参。

- [ ] **Step 1: 写出失败的模型和配置测试**

```python
from plugins.park_security.server.config import Settings
from plugins.park_security.server.models import CreateWorkOrder, EventAction, SecurityEvent


def test_settings_defaults_to_loopback_mock(monkeypatch):
    monkeypatch.delenv("PARK_SECURITY_MCP_HOST", raising=False)
    monkeypatch.delenv("PARK_SECURITY_DATA_MODE", raising=False)
    settings = Settings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8200
    assert settings.data_mode == "mock"


def test_action_models_require_operator_and_assignee():
    assert EventAction(event_id="event-night-001", operator_id="guard-01").operator_id == "guard-01"
    assert CreateWorkOrder(
        event_id="event-night-001", operator_id="guard-01", assignee="team-night"
    ).assignee == "team-night"
    assert SecurityEvent.model_validate({"event_id": "event-night-001", "park_id": "park-1"}).status == "open"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/infrastructure/plugins/test_park_security.py -q`

Expected: FAIL，提示 `plugins.park_security` 或其模型尚不存在。

- [ ] **Step 3: 创建最小模型与配置实现**

```python
# plugins/park_security/server/config.py
@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_mode: Literal["mock"]

    @classmethod
    def from_env(cls) -> "Settings":
        data_mode = os.getenv("PARK_SECURITY_DATA_MODE", "mock").strip().lower()
        if data_mode != "mock":
            raise ValueError("PARK_SECURITY_DATA_MODE must be mock")
        return cls(
            host=os.getenv("PARK_SECURITY_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("PARK_SECURITY_MCP_PORT", "8200")),
            data_mode="mock",
        )

# plugins/park_security/server/models.py
EventStatus = Literal["open", "confirmed", "work_order_created", "closed"]
RiskLevel = Literal["low", "medium", "high", "critical"]

class EventAction(BaseModel):
    event_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    note: str | None = None

class CreateWorkOrder(EventAction):
    assignee: str = Field(min_length=1)

def wrap_response(payload: Any) -> dict[str, Any]:
    return {"success": True, "data": payload, "raw": payload}
```

为所有 `SecurityEvent` 字段提供安全的默认值，使最小验证的 `event_id` 生成 `status="open"`、空 `alarm_ids`、空 `timeline` 和空审计记录；对所有标识字段使用 `Field(min_length=1)`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/infrastructure/plugins/test_park_security.py -q`

Expected: PASS，以上三个断言通过。

- [ ] **Step 5: 提交领域契约**

```bash
git add plugins/park_security tests/infrastructure/plugins/test_park_security.py
git commit -m "feat: define park security models"
```

### Task 2: 确定性告警场景与内存仓储

**Files:**
- Create: `plugins/park_security/server/mock_repository.py`
- Modify: `tests/infrastructure/plugins/test_park_security.py`

**Interfaces:**
- Consumes: Task 1 的 `SecurityAlarm`、`SecurityEvent`、`EvidenceItem`、`AuditRecord` 和 `WorkOrder`。
- Produces: `MockSecurityRepository`，提供 `list_events(park_id: str) -> list[SecurityEvent]`、`get_event(event_id: str) -> SecurityEvent | None`、`save_event(event: SecurityEvent) -> SecurityEvent`、`create_work_order(event_id: str, assignee: str, operator_id: str, note: str | None) -> WorkOrder` 和 `list_shift_context(park_id: str, area_id: str | None) -> dict[str, Any]`。
- Produces: 每个新仓储实例返回相同的三个事件：`event-night-001`、`event-access-002`、`event-fire-003`。

- [ ] **Step 1: 写出失败的固定场景测试**

```python
from plugins.park_security.server.mock_repository import MockSecurityRepository


def test_repository_exposes_three_correlated_mock_scenarios():
    events = MockSecurityRepository().list_events("park-1")
    assert [event.event_id for event in events] == [
        "event-night-001", "event-access-002", "event-fire-003"
    ]
    night, access, fire = events
    assert night.scenario == "night_abnormal_access"
    assert night.risk_level == "high"
    assert len(night.alarm_ids) == 2
    assert access.scenario == "access_failure_and_loitering"
    assert len(access.alarm_ids) == 3
    assert fire.risk_level == "critical"
    assert {item.source for item in fire.timeline} >= {"fire", "device"}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/infrastructure/plugins/test_park_security.py::test_repository_exposes_three_correlated_mock_scenarios -q`

Expected: FAIL，提示 `MockSecurityRepository` 尚不存在。

- [ ] **Step 3: 创建固定告警、事件和上下文数据**

```python
class MockSecurityRepository:
    def __init__(self) -> None:
        self._events = {
            "event-night-001": SecurityEvent(
                event_id="event-night-001", park_id="park-1",
                scenario="night_abnormal_access", risk_level="high",
                area_id="area-lab-01", responsible_party="team-night",
                recommended_plan="night_access_verification",
                alarm_ids=["alarm-access-001", "alarm-video-001"],
            ),
            # event-access-002: 三个门禁/巡更关联告警
            # event-fire-003: 烟感、温度、设备状态关联告警
        }
```

为三组事件填充 ISO 8601 UTC 时间、`building-a`、重点区域、截图摘要引用、值班/预约/设备状态证据和 `impact_scope`。`list_events` 和 `get_event` 返回 `model_copy(deep=True)`，避免读取方修改仓储状态。`save_event` 也保存深拷贝；`create_work_order` 使用稳定编号 `wo-<event_id>` 并在重复建单时抛出 `ValueError("work_order_exists")`。`list_shift_context` 返回重点区域、`guard-01` 当班信息、责任区域和一级/二级升级规则。

- [ ] **Step 4: 运行场景测试，确认通过**

Run: `pytest tests/infrastructure/plugins/test_park_security.py::test_repository_exposes_three_correlated_mock_scenarios -q`

Expected: PASS，三个事件、风险等级、告警数量和消防关联证据符合断言。

- [ ] **Step 5: 提交仓储**

```bash
git add plugins/park_security/server/mock_repository.py tests/infrastructure/plugins/test_park_security.py
git commit -m "feat: add park security mock scenarios"
```

### Task 3: 查询、风险摘要和人工闭环服务

**Files:**
- Create: `plugins/park_security/server/service.py`
- Modify: `tests/infrastructure/plugins/test_park_security.py`

**Interfaces:**
- Consumes: Task 1 的 `EventListQuery`、`EventAction`、`CreateWorkOrder` 与 Task 2 的 `MockSecurityRepository`。
- Produces: `SecurityService(repository: MockSecurityRepository)`，公开异步方法 `get_event_summary(park_id)`, `list_events(query)`, `get_event_detail(event_id)`, `get_shift_context(park_id, area_id=None)`, `confirm_event(action)`, `create_work_order(action)` 和 `close_event(action)`；每个方法返回稳定响应信封。
- Produces: 写操作状态机 `open -> confirmed -> work_order_created -> closed`，且 `close_event` 接受 `confirmed` 与 `work_order_created`。

- [ ] **Step 1: 写出失败的查询与闭环测试**

```python
def test_service_returns_event_timeline_and_summary():
    service = SecurityService(MockSecurityRepository())
    summary = asyncio.run(service.get_event_summary("park-1"))
    detail = asyncio.run(service.get_event_detail("event-fire-003"))
    assert summary["data"]["total_events"] == 3
    assert summary["data"]["risk_counts"]["critical"] == 1
    assert detail["data"]["recommended_plan"] == "fire_emergency_response"
    assert len(detail["data"]["timeline"]) >= 3


def test_service_requires_confirmation_before_work_order_and_records_audit():
    service = SecurityService(MockSecurityRepository())
    action = EventAction(event_id="event-night-001", operator_id="guard-01", note="现场核验")
    with pytest.raises(ValueError, match="event_not_confirmed"):
        asyncio.run(service.create_work_order(CreateWorkOrder(**action.model_dump(), assignee="team-night")))
    confirmed = asyncio.run(service.confirm_event(action))
    created = asyncio.run(service.create_work_order(CreateWorkOrder(**action.model_dump(), assignee="team-night")))
    closed = asyncio.run(service.close_event(action))
    assert confirmed["data"]["status"] == "confirmed"
    assert created["data"]["status"] == "work_order_created"
    assert closed["data"]["status"] == "closed"
    assert closed["data"]["review_report"]["event_id"] == "event-night-001"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/infrastructure/plugins/test_park_security.py -q`

Expected: FAIL，提示 `SecurityService` 尚不存在。

- [ ] **Step 3: 创建服务层与显式状态校验**

```python
class SecurityService:
    def __init__(self, repository: MockSecurityRepository) -> None:
        self.repository = repository

    async def confirm_event(self, action: EventAction) -> dict[str, Any]:
        event = self._require_event(action.event_id)
        if event.status != "open":
            raise ValueError("event_not_open")
        event.status = "confirmed"
        event.audit_records.append(self._audit("confirmed", action))
        return wrap_response(event.model_dump(mode="json"))

    async def create_work_order(self, action: CreateWorkOrder) -> dict[str, Any]:
        event = self._require_event(action.event_id)
        if event.status != "confirmed":
            raise ValueError("event_not_confirmed")
        work_order = self.repository.create_work_order(
            action.event_id, action.assignee, action.operator_id, action.note
        )
        event.status = "work_order_created"
        event.work_order_id = work_order.work_order_id
        event.audit_records.append(self._audit("work_order_created", action))
        self.repository.save_event(event)
        return wrap_response(event.model_dump(mode="json"))
```

`list_events` 使用 `EventListQuery` 中所有非空条件进行精确筛选，并按 `first_occurred_at` 升序返回精简事件卡片。`get_event_detail` 返回完整时间线、证据、影响范围、预案、工单和审计。`get_event_summary` 返回 `total_events`、风险/状态计数、`raw_alarm_count`、`merged_event_count`、`duplicate_alarm_count`、`effective_alarm_rate` 与 `average_risk_score`。`close_event` 对允许状态生成 `review_report`（事件标识、最终风险、处置过程、证据完整度、关闭时间），追加 `closed` 审计，保存后返回事件详情；不存在事件必须抛出 `ValueError("event_not_found")`。

- [ ] **Step 4: 运行服务测试，确认通过**

Run: `pytest tests/infrastructure/plugins/test_park_security.py -q`

Expected: PASS，汇总、时间线、确认前建单拒绝、状态转换、审计和复盘断言通过。

- [ ] **Step 5: 提交服务闭环**

```bash
git add plugins/park_security/server/service.py tests/infrastructure/plugins/test_park_security.py
git commit -m "feat: add park security event workflow"
```

### Task 4: MCP 工具清单和显式处理器

**Files:**
- Create: `plugins/park_security/plugin.yaml`
- Create: `plugins/park_security/server/main.py`
- Modify: `tests/infrastructure/plugins/test_park_security.py`

**Interfaces:**
- Consumes: Task 3 的 `SecurityService`；模块级 `service = SecurityService(MockSecurityRepository())`。
- Produces: 模块级 `mcp = MCPServer("park-security")` 和七个异步处理器：`get_event_summary`、`list_events`、`get_event_detail`、`get_shift_context`、`confirm_event`、`create_work_order`、`close_event`。
- Produces: 插件名 `park-security`、服务 ID `security`，远端工具名以 `security.` 开头。

- [ ] **Step 1: 写出失败的 MCP 契约测试**

```python
from plugins.park_security.server.main import (
    close_event, confirm_event, create_work_order, get_event_detail,
    get_event_summary, get_shift_context, list_events, mcp,
)


def test_mcp_handlers_have_explicit_parameters_and_expected_names():
    from mcp.server import MCPServer
    handlers = [get_event_summary, list_events, get_event_detail, get_shift_context,
                confirm_event, create_work_order, close_event]
    assert isinstance(mcp, MCPServer)
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for handler in handlers
        for parameter in inspect.signature(handler).parameters.values()
    )
    assert "operator_id" in inspect.signature(confirm_event).parameters
    assert "assignee" in inspect.signature(create_work_order).parameters
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/infrastructure/plugins/test_park_security.py::test_mcp_handlers_have_explicit_parameters_and_expected_names -q`

Expected: FAIL，提示 `plugins.park_security.server.main` 尚不存在。

- [ ] **Step 3: 编写插件清单与 MCP 适配处理器**

```yaml
api_version: minimal-agent/v1
id: park-security
version: 0.1.0
enabled: true
required: false
skills: []
mcp_servers:
  - id: security
    transport: streamable_http
    url_env: PARK_SECURITY_MCP_URL
    headers_env:
      Authorization: PARK_SECURITY_MCP_TOKEN
    allowed_tools:
      - name: security.get_event_summary
        side_effects: false
        idempotent: true
        timeout_seconds: 10
        result_size_limit: 262144
```

在同一 allowlist 中逐项声明其余六个工具。`list_events` 使用 `park_id: str` 加可选 `start_time`、`end_time`、`risk_level`、`status`；`get_event_detail` 使用 `event_id: str`；`get_shift_context` 使用 `park_id: str` 加可选 `area_id`；三个写处理器使用显式 `event_id`、`operator_id`、可选 `note`，建单额外接收 `assignee`。每个处理器构造 Task 1 定义的 Pydantic 请求模型后调用相同名称的 `service` 方法，禁止 `**kwargs`。最后使用 `mcp.run("streamable-http", host=settings.host, port=settings.port)`。

- [ ] **Step 4: 运行 MCP 契约及插件加载测试，确认通过**

Run: `pytest tests/infrastructure/plugins/test_park_security.py tests/infrastructure/plugins/test_plugin_loader.py -q`

Expected: PASS，处理器签名全部显式，清单可被既有加载器解析且不影响已有插件测试。

- [ ] **Step 5: 提交 MCP 接口**

```bash
git add plugins/park_security/plugin.yaml plugins/park_security/server/main.py tests/infrastructure/plugins/test_park_security.py
git commit -m "feat: expose park security mcp tools"
```

### Task 5: Compose、文档与端到端回归

**Files:**
- Modify: `docker-compose.yml`
- Create: `plugins/park_security/README.md`
- Modify: `README.md`
- Modify: `docs/MCP_INTEGRATION.md`
- Modify: `tests/infrastructure/plugins/test_park_security.py`

**Interfaces:**
- Consumes: Task 4 的插件清单，Agent 在容器网络内通过 `http://park_security:8200/mcp` 发现 `park-security.security.*` 工具。
- Produces: `park_security` Compose 服务和完整的 Mock 启动/调用说明。

- [ ] **Step 1: 写出失败的 Compose 配置测试**

```python
import yaml


def test_compose_wires_agent_to_park_security_service():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    agent = compose["services"]["agent"]
    security = compose["services"]["park_security"]
    assert agent["environment"]["PARK_SECURITY_MCP_URL"] == "${PARK_SECURITY_MCP_URL:-http://park_security:8200/mcp}"
    assert agent["depends_on"]["park_security"]["condition"] == "service_healthy"
    assert security["environment"]["PARK_SECURITY_DATA_MODE"] == "${PARK_SECURITY_DATA_MODE:-mock}"
```

Add `from pathlib import Path` and `import yaml` to the test module imports.

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/infrastructure/plugins/test_park_security.py::test_compose_wires_agent_to_park_security_service -q`

Expected: FAIL，提示 Compose 尚未定义 `park_security`。

- [ ] **Step 3: 添加 Compose 服务和用户文档**

```yaml
  park_security:
    build: .
    command: ["python", "-m", "plugins.park_security.server.main"]
    ports:
      - "127.0.0.1:8200:8200"
    environment:
      PARK_SECURITY_DATA_MODE: ${PARK_SECURITY_DATA_MODE:-mock}
      PARK_SECURITY_MCP_HOST: 0.0.0.0
      PARK_SECURITY_MCP_PORT: "8200"
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; s = socket.create_connection(('127.0.0.1', 8200), 2); s.close()"]
      interval: 2s
      timeout: 3s
      retries: 15
      start_period: 3s
```

向 Agent 环境增加 `PARK_SECURITY_MCP_URL` 与 `PARK_SECURITY_MCP_TOKEN`，并将 `park_security` 写入 `depends_on`。在插件 README 列出三种 Mock 场景、七个工具、`PARK_SECURITY_DATA_MODE=mock`、本地运行命令及“不处理原始视频/人脸/真实工单”的边界；根 README 和 MCP 集成文档加入对应环境变量与调用示例。

- [ ] **Step 4: 运行聚焦测试和完整回归**

Run: `pytest tests/infrastructure/plugins/test_park_security.py tests/infrastructure/plugins/test_park_energy.py -q`

Expected: PASS，安防与能耗插件测试通过。

Run: `pytest -q`

Expected: PASS，完整测试套件通过。

- [ ] **Step 5: 用 Compose 校验配置并提交交付物**

Run: `docker compose config`

Expected: exit code 0，且输出包含 `park_security`、`PARK_SECURITY_MCP_URL` 和健康检查。

```bash
git add docker-compose.yml README.md docs/MCP_INTEGRATION.md plugins/park_security tests/infrastructure/plugins/test_park_security.py
git commit -m "feat: document park security mock integration"
```

## Self-Review

- 规格覆盖：Task 1 定义领域契约和 Mock 模式；Task 2 覆盖三种关联告警场景与空间/值班上下文；Task 3 覆盖查询、风险摘要、人工确认、工单、审计和复盘；Task 4 覆盖七个 MCP 工具和正确副作用声明；Task 5 覆盖 Compose、用户文档和回归。
- 占位符检查：本文不含未填充内容、未定事项或“稍后处理”条目。
- 类型一致性：所有后续任务只使用 Task 1 定义的请求模型和 Task 2 定义的仓储接口；Task 4 的工具参数映射到 Task 3 同名服务方法。
