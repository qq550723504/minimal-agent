# park_energy Local Co-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run `minimal-agent` and the `park_energy` MCP service together through Compose with deterministic mock data.

**Architecture:** Add a `MockEnergyClient` behind an explicit `PARK_ENERGY_DATA_MODE=rest|mock` selector. Add a Compose park-energy service, wire the agent to its internal MCP URL, and make the agent host port configurable.

**Tech Stack:** Python 3.11, Pydantic, MCP 2.0, pytest, Docker Compose.

## Global Constraints

- Mock mode makes no network requests and uses deterministic values.
- Container ports remain agent `8000` and park-energy `8100`.
- Default Compose mode is mock; production defaults to rest.
- Existing REST paths, response envelope, and MCP tool names remain unchanged.

---

### Task 1: Add explicit data mode and deterministic mock client

**Files:**
- Create: `plugins/park_energy/server/mock_client.py`
- Modify: `plugins/park_energy/server/config.py`
- Modify: `plugins/park_energy/server/main.py`
- Test: `tests/infrastructure/plugins/test_park_energy.py`

- [ ] Write failing tests for default `rest`, explicit `mock`, and invalid mode; run `python -m pytest tests/infrastructure/plugins/test_park_energy.py -k data_mode -q` and confirm failure because `Settings.data_mode` is absent.
- [ ] Implement `Settings.data_mode: Literal["rest", "mock"]`, reading `PARK_ENERGY_DATA_MODE` and raising `ValueError("PARK_ENERGY_DATA_MODE must be rest or mock")` for unknown values; rerun the focused tests and confirm 3 pass.
- [ ] Write a failing async test that calls all five methods on two mock clients with identical `EnergyQuery`/`EnergyCompareQuery` values and asserts equal stable envelopes and preserved `park_id`; run `python -m pytest tests/infrastructure/plugins/test_park_energy.py -k mock -q` and confirm the missing-class failure.
- [ ] Implement `MockEnergyClient` with the same five async method signatures as `EnergyRESTClient`, fixed values derived only from query fields, no `httpx` calls, and `wrap_response` envelopes.
- [ ] Select `MockEnergyClient(settings)` in `main.py` when `settings.data_mode == "mock"`; otherwise keep `EnergyRESTClient(settings)`.
- [ ] Run `python -m pytest tests/infrastructure/plugins/test_park_energy.py -q`; confirm all focused tests pass.
- [ ] Commit with `git add plugins/park_energy/server/config.py plugins/park_energy/server/main.py plugins/park_energy/server/mock_client.py tests/infrastructure/plugins/test_park_energy.py` and `git commit -m "feat: add deterministic park energy mock mode"`.

### Task 2: Wire both services into Docker Compose

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.production.yml`

- [ ] Run `docker compose config --quiet` before edits and confirm the current configuration is valid.
- [ ] Change the agent mapping to `${AGENT_HOST_PORT:-8000}:8000`; retain the existing safe defaults for capability runtime, structured tool calling, and MCP allowlists, and expose the park-energy endpoint for direct MCP validation; agent registration requires an HTTPS gateway.
- [ ] Add `park_energy` using the existing build, command `python -m plugins.park_energy.server.main`, `PARK_ENERGY_DATA_MODE=mock`, `PARK_ENERGY_MCP_HOST=0.0.0.0`, port `8100`, loopback-only host mapping, and a Python TCP healthcheck; make agent depend on its health.
- [ ] Set production `PARK_ENERGY_DATA_MODE` to `${PARK_ENERGY_DATA_MODE:-rest}`, default production capability runtime and structured tool calling to `false` because production MCP HTTP requires HTTPS, and run `docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet`.
- [ ] Inspect `docker compose -f docker-compose.yml config` and confirm internal URL `park_energy:8100`, container agent port `8000`, and production default `rest`.
- [ ] Commit with `git add docker-compose.yml docker-compose.production.yml` and `git commit -m "feat: compose minimal agent with park energy"`.

### Task 3: Document and verify the integrated run

**Files:**
- Modify: `plugins/park_energy/README.md`
- Modify: `README.md`

- [ ] Document mock mode, Compose topology, native URL `http://127.0.0.1:8100/mcp`, and PowerShell startup: `$env:AGENT_HOST_PORT = "8001"; docker compose up --build`.
- [ ] Run `python -m pytest -q` and confirm 0 failures.
- [ ] Set `$env:AGENT_HOST_PORT = "8001"`, run `docker compose up --build -d`, and confirm `agent`, `park_energy`, and `prometheus` are running while `rembg-api` remains untouched.
- [ ] Verify `http://localhost:8001/` returns 200 and direct MCP discovery from park-energy lists five `energy.*` tools; do not claim local HTTP MCP is registered in agent because the manager requires HTTPS for HTTP MCP.
- [ ] Invoke one trend tool directly through the MCP client and verify `success: true`, requested `park_id`, and deterministic items.
- [ ] Run `docker compose down`, `git status --short`, and `git diff --check`; confirm no unrelated state changed.
- [ ] Commit documentation with `git add README.md plugins/park_energy/README.md` and `git commit -m "docs: document park energy mock co-run"`.
