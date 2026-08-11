# Park Security Mock Repository Split Design

## Goal

拆分 `plugins/park_security/server/mock_repository.py` 的职责，使告警归并、风险评估、Mock 场景构造和仓储状态管理可以独立理解与测试，同时保持现有导入路径和运行行为兼容。

## Scope

### In scope

- 将 `EventCorrelator` 与 `CorrelatedAlarmGroup` 移到 `correlation.py`。
- 将 `RiskAssessor` 与 `RiskAssessment` 移到 `risk.py`。
- 将固定告警、事件、证据和审计构造逻辑移到 `mock_fixtures.py`。
- 让 `mock_repository.py` 只负责内存状态、事件/工单 CRUD、值班上下文和组装依赖。
- 在 `mock_repository.py` 保留兼容导出，现有 `from ...mock_repository import EventCorrelator` 等调用无需修改。

### Out of scope

- 不改变 MCP 工具契约、响应结构、事件 ID、时间戳或状态机。
- 不引入真实数据库、设备适配器或新的业务场景。
- 不进行与文件拆分无关的算法重构。

## Proposed structure

```text
plugins/park_security/server/
├── correlation.py       # 归并窗口、空间邻接、主体/设备关联
├── risk.py              # 风险等级、影响范围、处置预案
├── mock_fixtures.py     # 固定告警、时间线、事件和审计构造
└── mock_repository.py   # 内存仓储、工单、值班上下文
```

依赖方向为 `models -> correlation/risk/mock_fixtures -> mock_repository -> service`。`mock_fixtures.py` 可以依赖归并和风险模型，但归并器和风险评估器不依赖仓储，避免循环依赖。

## Compatibility

`mock_repository.py` 重新导出 `CorrelatedAlarmGroup`、`EventCorrelator`、`RiskAssessment` 和 `RiskAssessor`。仓储保留 `_build_event` 等现有测试可见的兼容入口，内部实现改为调用 fixture 构造函数。

## Verification

- 运行现有安防插件、服务和全量测试。
- 增加模块导入测试，确认新模块可独立导入且兼容旧导入路径。
- 使用 `git diff --check` 检查拆分没有格式问题。
