# Agent Energy E2E Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Agent 通过已注册的 `park-energy` MCP 服务调用真实 `cent-energy` 趋势接口，完成自然语言请求到真实能耗结果的闭环。

**Architecture:** Agent 启动时加载 `plugins/park_energy/plugin.yaml`，通过 Streamable HTTP 发现能耗工具；park-energy 的 REST 客户端调用 Java `POST /api/agent/v1/energy/*`。直接运行 Agent 时安全开关默认关闭；开发 Compose 为完成闭环会显式开启，生产覆盖配置仍关闭。

**Tech Stack:** Python 3.11+, FastAPI, MCP SDK, httpx, pytest, Docker Compose。

## Global Constraints

- 只读能力，不新增数据库写操作。
- Java 成功码 `1000`、响应业务字段 `result` 必须被 Python 正确解包。
- 真实联调项目范围使用 `ENERGY_PROJECT_IDS=2709`，不得从用户自然语言拼接项目范围。
- 直接运行 Agent 的默认值仍为 `false`；开发 Compose 默认覆盖为 `true`，能耗数据模式默认使用 `rest`，Java 服务不可用时才显式改为 `mock`。

### Task 1: Local E2E runtime configuration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Test: `tests/config/test_deployment_config.py`

**Interfaces:**
- Produces documented environment variables for local Java-backed energy E2E.

- [x] **Step 1: Write the failing configuration test**

Assert Compose forwards `ENERGY_API_BASE_URL`, `ENERGY_PROJECT_IDS`, and enables the park-energy REST mode when explicitly configured.

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/config/test_deployment_config.py -q`
Expected: failure because the agent/park-energy service environments do not forward the Java-backed energy variables.

- [x] **Step 3: Write minimal Compose and README configuration**

Forward `ENERGY_API_BASE_URL`, `ENERGY_PROJECT_IDS`, `ENERGY_TREND_PATH`, `PARK_ENERGY_DATA_MODE`, and local MCP URL from `.env`; use container-safe MCP defaults and REST-backed energy defaults for development Compose.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/config/test_deployment_config.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

`git add docker-compose.yml README.md tests/config/test_deployment_config.py && git commit -m "feat: configure Java-backed energy E2E"`

### Task 2: MCP-to-Agent E2E test

**Files:**
- Create: `tests/api/test_energy_e2e_runtime.py`
- Modify: `tests/fixtures/mcp_energy_server.py` only if a focused fixture is needed.

**Interfaces:**
- Consumes the existing `MCPClientManager`, `PluginLoader`, and `handle_input_async` interfaces.
- Produces a regression test that discovers `energy.query_trend` and returns its structured result.

- [x] **Step 1: Write the failing test**

Create a local HTTP MCP fixture returning a deterministic trend result, configure a temporary plugin manifest matching `park-energy`, use a static planner returning a valid `energy.query_trend` ToolCall, and assert `handle_input_async()` returns the trend total.

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_energy_e2e_runtime.py -q`
Expected: FAIL before the fixture/manifest wiring is complete.

- [x] **Step 3: Implement only required fixture/wiring**

Reuse existing runtime lifecycle and adapter behavior; avoid production behavior changes unless the failing test identifies a real gap.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_energy_e2e_runtime.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

`git add tests/api/test_energy_e2e_runtime.py tests/fixtures && git commit -m "test: cover energy MCP agent loop"`

### Task 3: Real local verification and docs

**Files:**
- Modify: `docs/superpowers/plans/2026-08-13-energy-trend-agent-implementation.md`
- Modify: `plugins/park_energy/README.md`

- [x] **Step 1: Run focused regression suite**

Run: `pytest tests/infrastructure/plugins/test_park_energy.py tests/api/test_energy_e2e_runtime.py tests/config/test_deployment_config.py -q`.

- [x] **Step 2: Run real Java-backed Python call**

With Java on `127.0.0.1:19714`, `ENERGY_API_BASE_URL=http://127.0.0.1:19714`, `ENERGY_PROJECT_IDS=2709`, and `PARK_ENERGY_DATA_MODE=rest`, call `EnergyRESTClient.query_trend` for 2026-08-04 through 2026-08-10 and assert `total == 720.0`.

- [x] **Step 3: Document exact local startup order**

Document Java first, park-energy second, Agent third, plus the project scope; Compose provides the two runtime flags and container network defaults.

- [x] **Step 4: Run final verification**

Run the focused suite again and record the real result in the implementation plan.

- [x] **Step 5: Commit**

`git add docs plugins/park_energy/README.md && git commit -m "docs: document energy agent E2E startup"`
