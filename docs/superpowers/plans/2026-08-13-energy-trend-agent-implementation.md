# 能耗趋势 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 minimal-agent 的 `energy.query_trend` 通过 `cent-energy` 默认连接的 `cent_energy` 库返回按项目过滤的真实日电量趋势。

**Architecture:** 在 `cent-energy` 新建 Agent DAO、服务和 Controller，复用已有默认 MyBatis 数据源查询 `CMC_DEVICE_REPORT_DATA` 与 `CMC_DEVICE_METER_INFO`。Python `park_energy` 将 MCP 参数和可信项目范围映射为 Java POST 请求；不新增数据源，不访问 `cent_agent`。

**Tech Stack:** Java 8、Spring Boot 2.2.7、MyBatis-Plus、MyBatis XML、JUnit 5、Python 3.12、Pydantic、httpx、pytest。

## Global Constraints

- 使用现有默认 `spring.datasource` 和 `cent_energy`，不创建 `agent.datasource`。
- 使用 `CMC_DEVICE_REPORT_DATA.ACTIVE_ENERGY`、`CREATED_DATE`、`DEVICE_CODE`，并借助 `CMC_DEVICE_METER_INFO.PROJECT_ID` 过滤项目。
- 只读查询；不得提交真实数据库凭据或写入数据。
- 请求必须携带非空 `projectIds`；未来改由 Gateway 上下文提供。
- 日电量按最早/最晚采集时间的累计值计算，负差值和不足两条读数不计入。
- Java 接口为 `POST /api/agent/v1/energy/trend`，使用 `ResultJson`。
- Python 保留 Mock 和其余工具；仅调整 REST 的趋势调用。

---

### Task 1: Java 日电表读数查询

**Files:**

- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/MeterDailyReading.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dao/AgentEnergyDao.java`
- Create: `E:/code/cent-energy/src/main/resources/mapper/AgentEnergyMapper.xml`
- Test: `E:/code/cent-energy/src/test/java/com/xhwl/energy/agent/dao/AgentEnergyDaoTest.java`

**Interfaces:** `List<MeterDailyReading> findDailyReadings(LocalDate startDate, LocalDate endDate, List<Long> projectIds, List<String> meterIds)`；DTO 字段为 `meterId`、`date`、`firstReading`、`lastReading`、`readingCount`。

- [x] 先写失败的 DAO 契约测试：要求 Mapper 方法接收项目范围，且输出含电表、日期、首末读数和采样数。
- [ ] 运行 `mvn -Dtest=AgentEnergyDaoTest test`，确认因 DAO/DTO 缺失失败。
- [x] 新建 Mapper 接口/XML。SQL 必须以 `CMC_DEVICE_METER_INFO.DEVICE_CODE = CMC_DEVICE_REPORT_DATA.DEVICE_CODE` 连接，并使用 `PROJECT_ID IN (...)` 过滤；时间使用 `[startDate 00:00, endDate+1 00:00)`。每个电表日期按 `MIN(CREATED_DATE)` 与 `MAX(CREATED_DATE)` 找首末记录并取对应 `ACTIVE_ENERGY`，禁止用 `MIN/MAX(ACTIVE_ENERGY)` 替代时间首末值。
- [ ] 运行 `mvn -Dtest=AgentEnergyDaoTest test`，确认通过。
- [ ] 提交：`git add src/main/java/com/xhwl/energy/agent src/main/resources/mapper/AgentEnergyMapper.xml src/test/java/com/xhwl/energy/agent/dao/AgentEnergyDaoTest.java`，然后 `git commit -m "feat: query daily energy readings for agent"`。

### Task 2: Java 趋势服务和 HTTP 接口

**Files:**

- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyTrendQuery.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyTrendPoint.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyExtremum.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyDataQuality.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyTrendResult.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/service/AgentEnergyService.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/service/impl/AgentEnergyServiceImpl.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/controller/AgentEnergyController.java`
- Test: `E:/code/cent-energy/src/test/java/com/xhwl/energy/agent/service/AgentEnergyServiceImplTest.java`
- Test: `E:/code/cent-energy/src/test/java/com/xhwl/energy/agent/controller/AgentEnergyControllerTest.java`

**Interfaces:** `EnergyTrendResult queryTrend(EnergyTrendQuery query)`，`POST /api/agent/v1/energy/trend -> ResultJson<EnergyTrendResult>`。

- [ ] 写失败测试：同日 `10->15` 与 `20->18` 读数总量为 `5`、有效电表数为 `1`、无效读数数为 `1`；缺项目、反向日期或 32 天日期范围抛 `IllegalArgumentException`；无有效读数返回零总量和空序列。
- [ ] 运行 `mvn -Dtest=AgentEnergyServiceImplTest test`，确认因实现缺失失败。
- [x] 实现请求参数 `startDate`、`endDate`、`meterIds`、`projectIds`：日期必填、项目范围必填、跨度最大 31 天。逐行计算：样本数小于 2 增加缺失；负差值增加无效；否则累加日点。按日期排序，计算总量、两位小数日均、峰和谷。
- [ ] 实现 `/api/agent/v1/energy/trend` Controller，并用 `ResultJson.success` 包装成功结果。
- [ ] 运行 `mvn -Dtest=AgentEnergyServiceImplTest,AgentEnergyControllerTest test`，再运行 `mvn test`；均应通过。
- [ ] 提交：`git add src/main/java/com/xhwl/energy/agent src/test/java/com/xhwl/energy/agent`，然后 `git commit -m "feat: expose agent energy trend endpoint"`。

### Task 3: Python 趋势 REST 契约

**Files:**

- Modify: `E:/code/new/plugins/park_energy/server/config.py`
- Modify: `E:/code/new/plugins/park_energy/server/models.py`
- Modify: `E:/code/new/plugins/park_energy/server/rest_client.py`
- Modify: `E:/code/new/tests/infrastructure/plugins/test_park_energy.py`

- [ ] 写失败测试，要求 `query_trend` 向 `/api/agent/v1/energy/trend` 发送 POST，JSON 为 `{"startDate":"2026-08-04","endDate":"2026-08-10","meterIds":[],"projectIds":[101]}`；Java `{"code":200,"data":{"total":5}}` 解析为成功，HTTP 500、失败 ResultJson 与错误 JSON 为 `EnergyAPIError`。
- [ ] 运行 `pytest tests/infrastructure/plugins/test_park_energy.py -q`，确认因当前 GET 与旧路径失败。
- [x] 默认 `trend_path` 改为 `/api/agent/v1/energy/trend`。新增 `EnergyTrendRequest`，映射日期、可选 `building_id` 至 `meterIds`，并接收项目范围；增加有请求体上限、超时、请求头和错误转换的 `_post_json()`。只有 `query_trend` 改 POST；其余工具继续 GET。
- [ ] 运行 `pytest tests/infrastructure/plugins/test_park_energy.py -q`，确认通过。
- [ ] 提交：`git add plugins/park_energy/server/config.py plugins/park_energy/server/models.py plugins/park_energy/server/rest_client.py tests/infrastructure/plugins/test_park_energy.py`，然后 `git commit -m "feat: call agent energy trend endpoint"`。

### Task 4: 文档与联调

**Files:**

- Modify: `E:/code/new/plugins/park_energy/README.md`
- Modify: `E:/code/new/docs/superpowers/specs/2026-08-13-energy-trend-agent-design.md`

- [x] 记录 `PARK_ENERGY_DATA_MODE=rest`、`ENERGY_API_BASE_URL`、默认趋势路径和项目范围来源。
- [x] 记录手工请求：`Invoke-RestMethod -Method Post -Uri "http://localhost:9714/api/agent/v1/energy/trend" -ContentType "application/json" -Body '{"startDate":"2026-08-04","endDate":"2026-08-10","meterIds":[],"projectIds":[101]}'`。
- [ ] 运行 Java `mvn test` 与 Python `pytest tests/infrastructure/plugins/test_park_energy.py -q`；在真实 `cent_energy` 数据库有采样记录时，将响应总量与同口径 SQL 核对。
- [ ] 提交文档：`git add plugins/park_energy/README.md docs/superpowers/specs/2026-08-13-energy-trend-agent-design.md`，然后 `git commit -m "docs: document agent energy trend integration"`。

## Plan Self-Review

- 任务 1–2 实现 `cent_energy` 单数据源查询、项目过滤、统计规则和 Java 接口。
- 任务 3 实现 Python POST 契约且不破坏 Mock。
- 任务 4 覆盖配置、测试与真实数据核对。
