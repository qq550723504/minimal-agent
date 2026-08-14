# 能耗 Agent 展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有安防 Agent 页面中展示 `park-energy` 的五类只读能耗结果。

**Architecture:** 复用 structured handle API；后端将 namespaced MCP 工具结果映射为能耗 block，前端在同一聊天窗口中渲染趋势、排名、峰值、对比和异常卡片。数据仍由 `park-energy` 转发给 `cent-energy`，Agent 不直接访问数据库。

**Tech Stack:** FastAPI/Python、现有 capability runtime、原生 HTML/CSS/JavaScript、pytest。

## Global Constraints

- 不增加新的数据库连接。
- 不改变 `response_mode=text` 的返回格式。
- 能耗工具均为只读能力。
- 缺失字段和工具错误必须安全降级，不得伪造数值。

---

### Task 1: 后端能耗 block 映射

**Files:**
- Modify: `tests/api/test_server.py`
- Modify: `src/agent/application/requests.py`

- [ ] **Step 1: Write the failing tests**

添加测试，构造 namespaced `energy.query_trend`、`energy.query_ranking`、`energy.get_peak_value`、`energy.compare_period`、`energy.get_alarm_summary` 的 `ToolResult`，断言 `_build_response_blocks` 分别返回 `energy_trend`、`energy_ranking`、`energy_peak`、`energy_compare`、`energy_alarm`。

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest -q tests/api/test_server.py -k energy_blocks`

Expected: FAIL because the five tools currently map to `tool_result`.

- [ ] **Step 3: Implement minimal mapping and summaries**

在 `_STRUCTURED_BLOCK_TYPES` 中增加五个能耗工具映射，并在 `_response_message` 中为趋势、排名、峰值、对比和异常结果提供简短摘要；保留原始 `data` 不变。

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest -q tests/api/test_server.py -k energy_blocks`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/api/test_server.py src/agent/application/requests.py
git commit -m "feat: map energy tool results to response blocks"
```

### Task 2: 页面能耗卡片

**Files:**
- Modify: `tests/api/test_security_dashboard.py`
- Modify: `demos/park-security/index.html`

- [ ] **Step 1: Write the failing tests**

扩展页面静态测试，断言页面包含 `energy_trend`、`energy_ranking`、`energy_peak`、`energy_compare`、`energy_alarm` 和 `park-energy` 配置提示。

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest -q tests/api/test_security_dashboard.py`

Expected: FAIL because the page没有能耗 block 渲染标记。

- [ ] **Step 3: Implement minimal UI**

在 `renderResponseBlock` 中增加五类能耗卡片：趋势使用横向点列展示，排名使用列表，峰值/对比/异常使用统计网格；数组或字段缺失时显示 `—` 或空状态。补充页面上的能耗快捷问题。

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest -q tests/api/test_security_dashboard.py`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add tests/api/test_security_dashboard.py demos/park-security/index.html
git commit -m "feat: render energy cards in security dashboard"
```

### Task 3: 运行配置与回归验证

**Files:**
- Modify: `plugins/park_energy/README.md`

- [ ] **Step 1: Document combined runtime configuration**

补充安防+能耗共同启动示例，明确 `PARK_ENERGY_MCP_URL`、`PARK_ENERGY_DATA_MODE`、`ENERGY_API_BASE_URL`、`ENERGY_PROJECT_IDS`，并说明页面访问 `/security/`。

- [ ] **Step 2: Run focused and full tests**

Run: `python -m pytest -q tests/api/test_server.py tests/api/test_security_dashboard.py tests/application/test_executor.py`，再运行 `python -m pytest -q`。

Expected: 所有测试通过。

- [ ] **Step 3: Verify same-origin page**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/security/`。

Expected: HTTP 200。

- [ ] **Step 4: Commit**

```bash
git add plugins/park_energy/README.md
git commit -m "docs: document combined energy agent runtime"
```
