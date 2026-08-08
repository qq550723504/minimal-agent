# MCP Client Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect declared stdio and Streamable HTTP MCP Servers through the official SDK and register only approved remote tools in the capability runtime.

**Architecture:** `MCPClientManager` owns one entered SDK `Client` per configured Server in an `AsyncExitStack`. A transport factory enforces deployment security, an adapter paginates tool discovery and converts SDK results, and closures registered in `CapabilityRegistry` delegate calls back to the manager.

**Tech Stack:** Python 3.11, mcp 2.0.0, official MCP `Client`, `StdioServerParameters`, `stdio_client`, `streamable_http_client`, httpx2 from MCP SDK, asyncio, FastAPI lifespan, pytest-anyio.

## Global Constraints

- This plan requires the Capability Runtime Foundation and Plugin/Skill Runtime plans.
- Pin `mcp==2.0.0`; do not use v1 APIs, low-level JSON-RPC, SSE, or custom protocol code.
- Support only `stdio` and `streamable_http`.
- Discover all paginated tools but register only manifest `allowed_tools` entries.
- A missing declared tool is plugin initialization failure.
- HTTP redirects are disabled even though the SDK default follows redirects.
- Production HTTP MCP URLs require HTTPS and exact host allowlisting.
- stdio is administrator-authorized code execution: no shell wrappers, full host-environment inheritance, or unapproved executable paths; keep only the official SDK safe platform allowlist plus manifest-mapped variables.
- Tool business calls are not retried here; Agent runtime recovery owns retry decisions.

---

## File Map

- Create `src/agent/mcp/__init__.py`, `security.py`, `transport.py`, `adapter.py`, `manager.py`.
- Modify `requirements.txt` to pin MCP.
- Modify `src/agent/plugins/catalog.py` for MCP status updates.
- Modify `src/agent/server.py` to use FastAPI lifespan.
- Modify `src/agent/config.py` for MCP security settings.
- Modify `src/agent/observability.py` for MCP/tool metrics.
- Create `tests/fixtures/mcp_echo_server.py`.
- Create `tests/test_mcp_security.py`, `test_mcp_adapter.py`, `test_mcp_manager.py`, `test_mcp_transports.py`.
- Modify `tests/test_server.py`, `tests/test_deployment_config.py`.

### Task 1: Pin the SDK and validate transport security

**Files:**
- Modify: `requirements.txt`
- Create: `src/agent/mcp/__init__.py`
- Create: `src/agent/mcp/security.py`
- Modify: `src/agent/config.py`
- Test: `tests/test_mcp_security.py`

**Interfaces:**
- Produces: `validate_stdio_config(server, plugin_root, allowed_commands) -> ResolvedStdioConfig` and `validate_http_config(server, environ, allowed_hosts, production) -> ResolvedHTTPConfig`, including the validated IP address set.

- [ ] **Step 1: Write failing security tests**

```python
import pytest


@pytest.mark.parametrize("command", ["cmd", "powershell", "pwsh", "bash", "sh"])
def test_stdio_rejects_shell_wrappers(command, stdio_manifest, tmp_path):
    stdio_manifest.command = command
    with pytest.raises(MCPSecurityError, match="mcp_stdio_shell_forbidden"):
        validate_stdio_config(stdio_manifest, tmp_path, {command})


def test_http_requires_exact_allowed_https_host(http_manifest, monkeypatch):
    monkeypatch.setenv("DEMO_URL", "http://169.254.169.254/mcp")
    with pytest.raises(MCPSecurityError, match="mcp_http_https_required"):
        validate_http_config(http_manifest, os.environ, {"mcp.example.com"}, production=True)
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_mcp_security.py -q`

Expected: FAIL because MCP security functions are absent.

- [ ] **Step 3: Add dependencies, config, and exact validation**

Add `mcp==2.0.0`. Parse `AGENT_MCP_ALLOWED_HOSTS` and `AGENT_MCP_STDIO_ALLOWED_COMMANDS` as exact comma-separated values. Resolve stdio commands with `Path.resolve()` or `shutil.which()`, compare normalized absolute paths, reject known shell basenames, restrict `cwd` to the plugin root, and map only declared child variable names to existing host environment variable names.

For HTTP: resolve the URL from `url_env`, require `https` in production, reject credentials and fragments, compare a normalized hostname against the exact allowlist, resolve every address and reject loopback/private/link-local/multicast/reserved/unspecified values in production. Return the complete validated address set in `ResolvedHTTPConfig`; do not discard it after validation.

- [ ] **Step 4: Run security tests**

Run: `python -m pytest tests/test_mcp_security.py -q`

Expected: PASS, including Windows path normalization tests.

- [ ] **Step 5: Commit security boundaries**

```powershell
git add requirements.txt src/agent/config.py src/agent/mcp tests/test_mcp_security.py
git commit -m "feat: validate MCP transport security"
```

### Task 2: Build official SDK transports and lifecycle manager

**Files:**
- Create: `src/agent/mcp/transport.py`
- Create: `src/agent/mcp/manager.py`
- Test: `tests/test_mcp_manager.py`

**Interfaces:**
- Consumes: resolved configs and official MCP SDK.
- Produces: `MCPClientManager.start_server()`, `get_client()`, `stop_server()`, `close()`.

- [ ] **Step 1: Write a failing lifecycle test with an injected client factory**

```python
@pytest.mark.anyio
async def test_manager_enters_and_closes_each_client_once(fake_client_factory):
    manager = MCPClientManager(client_factory=fake_client_factory)
    await manager.start_server("demo.remote", resolved_http_config())
    assert manager.get_client("demo.remote").connected is True
    await manager.close()
    assert fake_client_factory.clients[0].exit_count == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_mcp_manager.py -q`

Expected: FAIL because `MCPClientManager` is missing.

- [ ] **Step 3: Implement transports with official APIs**

```python
def stdio_transport(config):
    params = StdioServerParameters(
        command=str(config.command),
        args=list(config.args),
        env=dict(config.env),
        cwd=str(config.cwd),
    )
    return stdio_client(params)


def http_transport(config, http_client):
    return streamable_http_client(
        config.url,
        http_client=http_client,
        terminate_on_close=True,
    )
```

Add `PinnedHostAsyncTransport`, a wrapper around the public `httpx2.AsyncHTTPTransport` API. It connects only to an address from `ResolvedHTTPConfig.addresses`, preserves the original HTTP `Host` value and TLS `sni_hostname`, and delegates HTTP/1.1, HTTP/2, streaming, and pooling to the library transport. It must not implement HTTP framing itself.

Create `httpx2.AsyncClient(headers=config.headers, follow_redirects=False, timeout=httpx2.Timeout(30.0, read=300.0), transport=pinned_transport, trust_env=False)` inside the same `AsyncExitStack`. Enter `Client(transport)` once and keep it alive until shutdown. Construction alone must not count as connected. On reconnect, resolve and validate a fresh address set before constructing a new pinned transport.

- [ ] **Step 4: Cover cleanup after partial startup failure**

```python
@pytest.mark.anyio
async def test_partial_startup_failure_closes_prior_clients(failing_second_factory):
    manager = MCPClientManager(client_factory=failing_second_factory)
    with pytest.raises(MCPConnectionError):
        await manager.start_server("demo.one", config_one())
        await manager.start_server("demo.two", config_two())
    await manager.close()
    assert failing_second_factory.clients[0].exit_count == 1
    assert manager.server_ids() == []
```

Verify an exception entering Server N closes Servers 1..N-1 and leaves no registered client. Run:

`python -m pytest tests/test_mcp_manager.py -q`

Expected: PASS.

Add a DNS rebinding regression test: validate a hostname against a safe loopback fixture under the explicit dev override, change the mocked resolver to a different address before the MCP handshake, and assert the connection still targets only the address captured in `ResolvedHTTPConfig`.

- [ ] **Step 5: Commit lifecycle management**

```powershell
git add src/agent/mcp/transport.py src/agent/mcp/manager.py tests/test_mcp_manager.py
git commit -m "feat: manage MCP client lifecycles"
```

### Task 3: Discover and register allowlisted MCP tools

**Files:**
- Create: `src/agent/mcp/adapter.py`
- Modify: `src/agent/mcp/manager.py`
- Modify: `src/agent/plugins/catalog.py`
- Test: `tests/test_mcp_adapter.py`

**Interfaces:**
- Consumes: SDK `Client.list_tools()` / `call_tool()`, `AllowedToolManifest`, `CapabilityRegistry`.
- Produces: `discover_tools(client) -> list[Tool]`, `register_server_tools(plugin_id, server_id, client, allowed, registry) -> list[ToolSpec]`, and normalized remote invocation.

- [ ] **Step 1: Write failing pagination and allowlist tests**

```python
@pytest.mark.anyio
async def test_discovery_paginates_and_registers_only_allowlist(fake_paged_client):
    registered = await register_server_tools(
        plugin_id="demo",
        server_id="remote",
        client=fake_paged_client,
        allowed=[AllowedToolManifest(name="second", side_effects=False, idempotent=True)],
        registry=CapabilityRegistry(),
    )
    assert [spec.name for spec in registered] == ["demo.remote.second"]
    assert fake_paged_client.cursors == [None, "next"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_mcp_adapter.py -q`

Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Implement schema and result conversion**

Loop until `next_cursor is None`. For every allowed tool create a ToolSpec using `tool.input_schema`, the manifest's timeout/size/retry metadata, `source=ToolSource.MCP`, and the full namespaced name.

Invocation must call the remote unqualified name. If `result.is_error` is true, raise `ToolExecutionError(error_code="mcp_tool_error", retryable=False)`. Prefer `result.structured_content`; otherwise convert supported text content blocks to a bounded list of JSON dictionaries without guessing a combined JSON value.

Add `MCPClientManager.start_catalog(catalog: PluginCatalog, registry: CapabilityRegistry) -> None`. It starts enabled Servers in stable `<plugin-id>.<server-id>` order and stages all handlers for one Plugin before calling atomic `registry.register_many()`. If any Server or tool in an optional Plugin fails, close every client started for that Plugin and register none of its tools; update its status. Re-raise a sanitized `RequiredPluginError` for required failures.

- [ ] **Step 4: Test missing tools, duplicate namespaces, structured and text results**

```python
@pytest.mark.anyio
async def test_missing_declared_tool_registers_nothing(fake_client):
    registry = CapabilityRegistry()
    with pytest.raises(MCPToolDiscoveryError, match="declared_tool_missing"):
        await register_server_tools(
            "demo", "remote", fake_client.with_tools([]),
            [AllowedToolManifest(name="required", side_effects=False, idempotent=True)],
            registry,
        )
    assert registry.list_specs() == []


@pytest.mark.anyio
async def test_remote_error_is_not_treated_as_success(fake_client, registry):
    fake_client.call_result = SimpleNamespace(
        is_error=True,
        structured_content=None,
        content=[TextContent(type="text", text="denied")],
    )
    await register_server_tools(
        "demo", "remote", fake_client,
        [AllowedToolManifest(name="search", side_effects=False, idempotent=True)],
        registry,
    )
    result = await registry.invoke(
        ToolCall(call_id="1", tool="demo.remote.search", arguments={}),
        ToolInvocationContext(),
    )
    assert result.error_code == "mcp_tool_error"
```

Add `test_structured_content_is_preserved`, `test_text_blocks_remain_typed_list`, and `test_namespace_collision_is_atomic` with exact content and registry assertions.

Run: `python -m pytest tests/test_mcp_adapter.py tests/test_capability_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit MCP adaptation**

```powershell
git add src/agent/mcp src/agent/plugins/catalog.py tests/test_mcp_adapter.py
git commit -m "feat: register allowlisted MCP tools"
```

### Task 4: Exercise real in-memory, stdio, and Streamable HTTP transports

**Files:**
- Create: `tests/fixtures/mcp_echo_server.py`
- Create: `tests/test_mcp_transports.py`

**Interfaces:**
- Consumes: official `MCPServer`, in-memory `Client(server)`, stdio fixture, HTTP fixture.
- Produces: contract evidence for both supported wire transports.

- [ ] **Step 1: Add an official SDK echo Server fixture**

```python
from mcp.server import MCPServer

mcp = MCPServer("test-echo")


@mcp.tool()
def echo(message: str) -> dict[str, str]:
    return {"message": message}


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Prove the in-memory adapter contract first**

Run: `python -m pytest tests/test_mcp_transports.py::test_in_memory_client_contract -q`

Expected: PASS using `async with Client(mcp)` and no socket or subprocess.

- [ ] **Step 3: Add stdio and HTTP transport tests**

Launch stdio with `sys.executable` in the command allowlist. Launch Streamable HTTP on `127.0.0.1` only under an explicit test/dev override, select a free port, and always terminate the fixture in `finally`.

- [ ] **Step 4: Run transport tests without external SaaS**

Run: `python -m pytest tests/test_mcp_transports.py -q`

Expected: PASS for in-memory, stdio, and Streamable HTTP. No test may use a public hostname or credential.

- [ ] **Step 5: Commit transport contracts**

```powershell
git add tests/fixtures/mcp_echo_server.py tests/test_mcp_transports.py
git commit -m "test: cover supported MCP transports"
```

### Task 5: Integrate startup status and observability

**Files:**
- Modify: `src/agent/server.py:48-57`
- Modify: `src/agent/observability.py:8-28`
- Modify: `src/agent/plugins/catalog.py`
- Modify: `tests/test_server.py`
- Modify: `tests/test_plugin_api.py`

**Interfaces:**
- Consumes: `PluginLoader`, `MCPClientManager`.
- Produces: FastAPI lifespan startup/shutdown and sanitized MCP status.

- [ ] **Step 1: Write failing lifespan tests**

Verify an optional failed MCP plugin leaves `/` healthy and reports `error_code`, while a required failure prevents TestClient startup.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_server.py tests/test_plugin_api.py -q`

Expected: FAIL because MCP clients are not started by lifespan.

- [ ] **Step 3: Replace startup/shutdown decorators with one lifespan**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_memory()
    catalog = PluginLoader(Path(PLUGIN_DIR)).load_all()
    manager = MCPClientManager()
    if CAPABILITY_RUNTIME_ENABLED:
        await manager.start_catalog(catalog, get_capability_registry())
    start_queue()
    app.state.plugin_catalog = catalog
    app.state.mcp_manager = manager
    try:
        yield
    finally:
        stop_queue()
        await manager.close()
        save_memory()
```

Add bounded-label metrics for plugin load count, MCP connection status, tool calls, tool duration, and unknown outcomes. Never label by prompt, arguments, result, URL, or user ID.

Extend `/api/tools` entries additively with `source`, `plugin_id`, `input_schema`, `side_effects`, and `idempotent`, populated from ToolSpec. Preserve `name` and `description` for existing clients and never return handlers or expanded transport configuration.

- [ ] **Step 4: Run focused and complete tests**

Run: `python -m pytest tests/test_server.py tests/test_plugin_api.py tests/test_mcp_*.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit integration**

```powershell
git add src/agent/server.py src/agent/observability.py src/agent/plugins/catalog.py tests/test_server.py tests/test_plugin_api.py
git commit -m "feat: start MCP clients with the application"
```

## Plan Completion Gate

Run:

```powershell
python -m pip check
python -m pytest -q
git diff --check
```

Expected: all commands succeed. Confirm with `pip show mcp` that version is exactly `2.0.0` and inspect process lists after tests to ensure the stdio fixture is gone.
