# Energy Agent Java Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `cent-energy` 增加能耗排名、周期对比、异常摘要三个只读 Agent 接口，并接入 `park-energy`。

**Architecture:** 复用 `AgentEnergyDao` 查询 `cent_energy` 的电表累计读数，服务层统一执行项目范围、日期范围和读数质量规则。Controller 增加三个 POST 接口；Python REST 客户端和 MCP 工具保持现有模式，仅增加对应请求映射。

**Tech Stack:** Java 8, Spring Boot 2.2, MyBatis-Plus, MySQL, Python, httpx, MCP SDK, pytest。

## Global Constraints

- 三个接口均为只读，不新增表，不访问 `cent_agent`。
- 所有查询必须要求非空 `projectIds` 并进行项目过滤。
- 日期范围最大 31 天；比较接口的两个周期分别校验。
- `ACTIVE_ENERGY` 负增长计为异常，不计入正常能耗汇总。
- 默认 Mock 与 Agent 安全开关保持不变。

### Task 1: Java DTO、DAO 和服务接口

**Files:**
- Create: `cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyRankingQuery.java`
- Create: `cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyRankingResult.java`
- Create: `cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyComparisonQuery.java`
- Create: `cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyComparisonResult.java`
- Create: `cent-energy/src/main/java/com/xhwl/energy/agent/dto/EnergyAnomalyResult.java`
- Modify: `cent-energy/src/main/java/com/xhwl/energy/agent/dao/AgentEnergyDao.java`
- Modify: `cent-energy/src/main/resources/mapper/AgentEnergyMapper.xml`
- Modify: `cent-energy/src/main/java/com/xhwl/energy/agent/service/AgentEnergyService.java`
- Modify: `cent-energy/src/main/java/com/xhwl/energy/agent/service/impl/AgentEnergyServiceImpl.java`
- Test: `cent-energy/src/test/java/com/xhwl/energy/agent/service/AgentEnergyServiceImplTest.java`

**Interfaces:**
- `EnergyRankingResult queryRanking(EnergyRankingQuery query)` returns ordered meter totals.
- `EnergyComparisonResult compare(EnergyComparisonQuery query)` returns current total, baseline total, delta and percentage.
- `EnergyAnomalyResult summarizeAnomalies(EnergyTrendQuery query)` returns invalid/missing counts and affected meter-days.

- [x] Write failing service tests for ranking order, comparison percentage, and anomaly counts.
- [x] Run Java focused tests and observe missing DTO/service methods.
- [x] Implement DTOs, DAO queries, validation and service aggregation.
- [x] Run focused Java tests until green.
- [x] Commit Java capability implementation (`27eb971`).

### Task 2: Java Controller endpoints

**Files:**
- Modify: `cent-energy/src/main/java/com/xhwl/energy/agent/controller/AgentEnergyController.java`
- Test: `cent-energy/src/test/java/com/xhwl/energy/agent/controller/AgentEnergyControllerTest.java`

**Interfaces:**
- `POST /api/agent/v1/energy/ranking`
- `POST /api/agent/v1/energy/compare`
- `POST /api/agent/v1/energy/anomalies`

- [x] Add controller methods for request routing and `ResultJson.success` wrapping.
- [x] Implement three controller methods.
- [x] Verify the packaged service exposes all three routes.
- [x] Commit endpoint changes with Java capability implementation (`27eb971`).

### Task 3: Python park-energy integration

**Files:**
- Modify: `plugins/park_energy/server/models.py`
- Modify: `plugins/park_energy/server/rest_client.py`
- Modify: `plugins/park_energy/server/main.py`
- Modify: `plugins/park_energy/plugin.yaml`
- Test: `tests/infrastructure/plugins/test_park_energy.py`

**Interfaces:**
- REST paths: `/api/agent/v1/energy/ranking`, `/api/agent/v1/energy/compare`, `/api/agent/v1/energy/anomalies`.
- MCP tools: `energy.query_ranking`, `energy.compare_period`, `energy.get_anomaly_summary`.

- [x] Add request mapping and Java `result` unwrapping coverage.
- [x] Implement REST methods and MCP handlers.
- [x] Run Python plugin tests (`13 passed`).
- [x] Commit Python integration (`4cad1e8`).

### Task 4: Build and real-data verification

**Files:**
- Modify: `plugins/park_energy/README.md`
- Modify: this plan file

- [x] Run Java `mvn test` with the isolated compatible `cent-common` artifact (`4 tests passed`).
- [x] Run Python focused tests (`13 passed`).
- [x] Start the local Java instance and call all three endpoints with project `2709`.
- [x] Record response samples: ranking 2 meters, comparison `720` vs `360`, anomaly affected meter-days `15`.
- [x] Commit documentation and configuration (`b027790`).
