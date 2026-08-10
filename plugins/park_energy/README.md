# park-energy plugin

`park-energy` is a minimal MCP server that exposes energy-related tools through either an upstream REST API or deterministic local mock data.

## Environment Variables

```powershell
$env:PARK_ENERGY_DATA_MODE = "rest"
$env:ENERGY_API_BASE_URL = "https://energy.example.com"
$env:ENERGY_API_TOKEN = "<secret>"
$env:ENERGY_API_TOKEN_HEADER = "Authorization"
$env:ENERGY_API_TOKEN_PREFIX = "Bearer"
$env:ENERGY_API_TIMEOUT_SECONDS = "10"
$env:ENERGY_TREND_PATH = "/api/energy/trend"
$env:ENERGY_RANKING_PATH = "/api/energy/ranking"
$env:ENERGY_PEAK_PATH = "/api/energy/peak"
$env:ENERGY_COMPARE_PATH = "/api/energy/compare"
$env:ENERGY_ALARMS_PATH = "/api/energy/alarms"
$env:PARK_ENERGY_MCP_HOST = "127.0.0.1"
$env:PARK_ENERGY_MCP_PORT = "8100"
$env:ENERGY_API_MAX_RESPONSE_BYTES = "1048576"
```

- Override `ENERGY_*_PATH` values if your backend routes differ.
- `ENERGY_API_TOKEN` is optional if the API is open.
- `PARK_ENERGY_DATA_MODE` accepts `rest` or `mock` and defaults to `rest`.
- In `mock` mode, all five tools return repeatable sample data and make no upstream request.

## Run locally

From the repository root:

```powershell
python -m plugins.park_energy.server.main
```

The server listens on `PARK_ENERGY_MCP_HOST` and `PARK_ENERGY_MCP_PORT`.
The default host is loopback so the unauthenticated MCP endpoint is not exposed
to the network. If you set the host to `0.0.0.0`, put the server behind an
authenticated, network-restricted gateway.

For local development without an energy API:

```powershell
$env:PARK_ENERGY_DATA_MODE = "mock"
$env:PARK_ENERGY_MCP_HOST = "127.0.0.1"
$env:PARK_ENERGY_MCP_PORT = "8100"
python -m plugins.park_energy.server.main
```

The mock server remains available at `http://127.0.0.1:8100/mcp`.

## Run with minimal-agent in Compose

The repository Compose file starts `agent`, `park_energy`, and Prometheus.
The development default uses mock data and exposes park-energy at
`http://park_energy:8100/mcp` over the Compose network. If host port `8000`
is already occupied, use another host port without changing the container port:

```powershell
$env:AGENT_HOST_PORT = "8001"
docker compose up --build
```

The agent is then available at `http://localhost:8001/`, and park-energy is
available directly at `http://127.0.0.1:8100/mcp`. The two services run in
parallel, but the agent's current MCP manager requires HTTPS for HTTP MCP
targets, so this local HTTP endpoint is not advertised as an agent plugin.
Use an HTTPS gateway in front of park-energy before configuring agent plugin
registration. For native processes, the same direct MCP URL can be used by an
MCP client that explicitly permits loopback HTTP in development/test code.

## MiniAgent integration

```powershell
$env:AGENT_CAPABILITY_RUNTIME_ENABLED = "true"
$env:AGENT_STRUCTURED_TOOL_CALLING_ENABLED = "true"
$env:AGENT_MCP_ALLOWED_HOSTS = "energy.example.com"
$env:PARK_ENERGY_MCP_URL = "https://energy.example.com/mcp"
$env:PARK_ENERGY_MCP_TOKEN = "<secret>"
```

Start MiniAgent and check `/api/tools` to confirm registration.

## Tools

- `energy.query_trend`
  - Required: `park_id`, `start_time`, `end_time`
  - Optional: `building_id`, `energy_type` (`electricity` default), `granularity` (`day` default)
- `energy.query_ranking`
- `energy.get_peak_value`
- `energy.compare_period`
- `energy.get_alarm_summary`

## Plugin metadata

- Plugin ID: `park-energy`
- Transport: `streamable_http`
- Default port: `8100`
