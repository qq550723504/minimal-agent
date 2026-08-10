# park-energy plugin

`park-energy` is a minimal MCP server that exposes energy-related tools by wrapping REST endpoints.

## Environment Variables

```powershell
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
$env:PARK_ENERGY_MCP_HOST = "0.0.0.0"
$env:PARK_ENERGY_MCP_PORT = "8100"
```

- Override `ENERGY_*_PATH` values if your backend routes differ.
- `ENERGY_API_TOKEN` is optional if the API is open.

## Run locally

From the repository root:

```powershell
python -m plugins.park_energy.server.main
```

The server listens on `PARK_ENERGY_MCP_HOST` and `PARK_ENERGY_MCP_PORT`.

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