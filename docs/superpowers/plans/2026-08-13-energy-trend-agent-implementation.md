# 能耗趋势 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 minimal-agent 的 `energy.query_trend` 调用 `cent-energy`，从 `cent_agent` 的真实累计读数返回逐日能耗趋势。

**Architecture:** `cent-energy` 新增只读 `agent.datasource`，原默认数据源仍连接 `cent_energy`。专用 DAO 读取日电表首末值，服务层计算电量与质量指标；`park_energy` 将 MCP 参数转换为 Java POST 请求。

**Tech Stack:** Java 8、Spring Boot 2.2.7、Druid、JDBC Template、JUnit 5、Python 3.12、Pydantic、httpx、pytest。

## Global Constraints

- 不改变默认 `spring.datasource`、既有管理接口或已有表。
- `agent.datasource` 只读连接 `cent_agent`，凭据必须来自部署配置，禁止提交。
- 日电量为时间末读数减时间首读数；负差值不计入总量。
- 日期范围含首尾、最大 31 天；单日不足两条读数的不参与总量。
- Java 接口固定为 `POST /api/agent/v1/energy/trend`，用 `ResultJson` 包装。
- 保留 Python Mock 模式和其余工具，本次仅变更 REST `query_trend`。

---

### Task 1: Java 只读数据源与日电表读数 DAO

**Files:**

- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/config/AgentDataSourceProperties.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/config/AgentDataSourceConfig.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dto/MeterDailyReading.java`
- Create: `E:/code/cent-energy/src/main/java/com/xhwl/energy/agent/dao/AgentEnergyDao.java`
- Modify: `E:/code/cent-energy/src/main/resources/application-dev.properties`
- Test: `E:/code/cent-energy/src/test/java/com/xhwl/energy/agent/dao/AgentEnergyDaoTest.java`

**Interfaces:** Produces `List<MeterDailyReading> findDailyReadings(LocalDate startDate, LocalDate endDate, List<String> meterIds)`; each element has `meterId`、`date`、`firstReading`、`lastReading`、`readingCount`。

- [ ] Write a failing row-mapping test that asserts `AgentEnergyDao.mapRow(row("meter-1", "2026-08-04", "100.2", "113.7", 4))` produces the five expected fields.
- [ ] Run `mvn -Dtest=AgentEnergyDaoTest test`; expected compilation failure because the DAO and DTO do not exist.
- [ ] Add `@ConfigurationProperties` for `agent.datasource.url`、`username`、`password`、`driver-class-name`、`maximum-pool-size`, and an isolated Druid `agentJdbcTemplate`. Add only variable references—not credentials—to `application-dev.properties`.
- [ ] Implement the DAO with named parameters and the range `[startDate 00:00, endDate+1 00:00)`. SQL must determine the first and last values using `MIN(read_time)` and `MAX(read_time)` per `device_id` and natural date, joining back to obtain `read_num`; it must never substitute `MIN(read_num)`/`MAX(read_num)`.
- [ ] Run `mvn -Dtest=AgentEnergyDaoTest test`; expected PASS.
- [ ] Commit: `git add src/main/java/com/xhwl/energy/agent src/main/resources/application-dev.properties src/test/java/com/xhwl/energy/agent/dao/AgentEnergyDaoTest.java` then `git commit -m "feat: add agent energy read-only datasource"`.

### Task 2: Java 趋势服务与 HTTP 接口

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

**Interfaces:** Consumes the DAO from Task 1. Produces `EnergyTrendResult queryTrend(EnergyTrendQuery query)`. Exposes `ResultJson<EnergyTrendResult>`.

- [ ] Write failing tests: two meter readings `10->15` and `20->18` must produce total `5`, valid meter count `1`, invalid count `1`; a range from `2026-08-01` to `2026-09-01` must throw `IllegalArgumentException`.
- [ ] Run `mvn -Dtest=AgentEnergyServiceImplTest test`; expected compilation failure.
- [ ] Implement `EnergyTrendQuery(startDate, endDate, meterIds, projectIds)` with required dates, non-reversed range and inclusive maximum of 31 days. `projectIds` remains in the contract but does not reach the DAO.
- [ ] For each row: `readingCount < 2` increments missing count; negative difference increments invalid count and `invalidMeterCount`; otherwise add difference and increment `meterCount`. Sort series by date. Compute total, average (`HALF_UP`, 2 decimals), peak and valley. Return zero total, zero average, empty series and null extrema when no valid point exists.
- [ ] Add controller `@RequestMapping("/api/agent/v1/energy")`, `@PostMapping("/trend")`, returning `ResultJson.success(service.queryTrend(query))`.
- [ ] Run `mvn -Dtest=AgentEnergyServiceImplTest,AgentEnergyControllerTest test` then `mvn test`; expected PASS.
- [ ] Commit: `git add src/main/java/com/xhwl/energy/agent src/test/java/com/xhwl/energy/agent`; `git commit -m "feat: expose agent energy trend endpoint"`.

### Task 3: Python 趋势 REST 契约

**Files:**

- Modify: `E:/code/new/plugins/park_energy/server/config.py`
- Modify: `E:/code/new/plugins/park_energy/server/models.py`
- Modify: `E:/code/new/plugins/park_energy/server/rest_client.py`
- Modify: `E:/code/new/tests/infrastructure/plugins/test_park_energy.py`

**Interfaces:** Consumes `EnergyQuery`; produces existing `{success, data, raw}` tool envelope.

- [ ] Add a failing fake-HTTP test requiring POST `/api/agent/v1/energy/trend` with `{"startDate":"2026-08-04","endDate":"2026-08-10","meterIds":[],"projectIds":[]}`. It must assert that Java `{"code":200,"data":{"total":5}}` maps to successful tool data, while HTTP 500 and malformed JSON raise `EnergyAPIError`.
- [ ] Run `pytest tests/infrastructure/plugins/test_park_energy.py -q`; expected failure because the client uses GET and `/api/energy/trend`.
- [ ] Change `trend_path` default to `/api/agent/v1/energy/trend`. Add `EnergyTrendRequest` with `startDate`、`endDate`、`meterIds`、`projectIds`; build dates via `query.start_time[:10]` and `query.end_time[:10]`. Only map nonempty `building_id` to one `meterIds` element.
- [ ] Add bounded `_post_json()` with the same headers, timeout, max-response-size and error translations as `_get()`. Route only `query_trend()` through POST; retain GET for remaining tools. Treat a failed Java ResultJson code as `EnergyAPIError`, not a success envelope.
- [ ] Run `pytest tests/infrastructure/plugins/test_park_energy.py -q`; expected PASS.
- [ ] Commit: `git add plugins/park_energy/server/config.py plugins/park_energy/server/models.py plugins/park_energy/server/rest_client.py tests/infrastructure/plugins/test_park_energy.py`; `git commit -m "feat: call agent energy trend endpoint"`.

### Task 4: Operator documentation and end-to-end validation

**Files:**

- Modify: `E:/code/new/plugins/park_energy/README.md`
- Modify: `E:/code/new/docs/superpowers/specs/2026-08-13-energy-trend-agent-design.md`

- [ ] Document `PARK_ENERGY_DATA_MODE=rest`, `ENERGY_API_BASE_URL` and the default Agent trend path. State that `agent.datasource.*` values come only from deployment configuration.
- [ ] Add the exact manual check: `Invoke-RestMethod -Method Post -Uri "http://localhost:9714/api/agent/v1/energy/trend" -ContentType "application/json" -Body '{"startDate":"2026-08-04","endDate":"2026-08-10","meterIds":[],"projectIds":[]}'`.
- [ ] Verify the response contains `total`, `averageDaily`, `series`, `peak`, `valley`, `dataQuality`; run `mvn test` in `E:/code/cent-energy` and `pytest tests/infrastructure/plugins/test_park_energy.py -q` in `E:/code/new`.
- [ ] With external datasource configuration present, run the manual check and compare `total` against the approved SQL calculation. Otherwise report live verification as blocked on deployment configuration, without writing database data.
- [ ] Commit: `git add plugins/park_energy/README.md docs/superpowers/specs/2026-08-13-energy-trend-agent-design.md`; `git commit -m "docs: document agent energy trend integration"`.

## Plan Self-Review

- Tasks 1–2 cover isolated real-data access, all calculation rules and the Java endpoint.
- Task 3 preserves the MCP contract and Mock behavior while implementing the Java REST protocol.
- Task 4 documents configuration and proves tests plus live behavior when safe configuration exists.
- The DAO, service, controller and Python type names are identical across all tasks.
