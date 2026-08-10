from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from src.agent.security.auth import get_metrics_access

if TYPE_CHECKING:
    from src.agent.domain.capabilities.models import ToolResult, ToolSpec
    from src.agent.infrastructure.plugins.catalog import PluginCatalog

REQUEST_COUNT = Counter(
    "agent_request_count",
    "Total number of HTTP requests received by the agent",
    ["method", "endpoint", "http_status"],
)
REQUEST_LATENCY = Histogram(
    "agent_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)
PLUGIN_LOAD_COUNT = Counter(
    "agent_plugin_load_total",
    "Total plugins observed while loading a catalog",
    ["state"],
)
MCP_CONNECTION_STATUS = Gauge(
    "agent_mcp_connection_status",
    "Current MCP connection count by sanitized status",
    ["status"],
)
TOOL_CALL_COUNT = Counter(
    "agent_tool_calls_total",
    "Total structured tool calls by bounded source and outcome",
    ["source", "status"],
)
TOOL_CALL_DURATION = Histogram(
    "agent_tool_call_duration_seconds",
    "Structured tool call duration by bounded source",
    ["source"],
)
TOOL_UNKNOWN_OUTCOME_COUNT = Counter(
    "agent_tool_unknown_outcome_total",
    "Structured tool calls with an unknown outcome by bounded source",
    ["source"],
)


def record_catalog_startup(catalog: "PluginCatalog", connected_servers: int) -> None:
    """Record deployment-level plugin and MCP state without dynamic labels."""
    states = {"enabled": 0, "disabled": 0}
    for status in catalog.statuses.values():
        states[status.state] += 1
    for state, count in states.items():
        PLUGIN_LOAD_COUNT.labels(state).inc(count)
    MCP_CONNECTION_STATUS.labels("connected").set(connected_servers)
    MCP_CONNECTION_STATUS.labels("failed").set(catalog.mcp_failure_count)


def observe_tool_call(spec: "ToolSpec | None", result: "ToolResult", duration: float) -> None:
    """Observe a capability invocation without capturing arguments or content."""
    source = spec.source.value if spec is not None else "unknown"
    status = result.status.value
    TOOL_CALL_COUNT.labels(source, status).inc()
    TOOL_CALL_DURATION.labels(source).observe(duration)
    if status == "unknown_outcome":
        TOOL_UNKNOWN_OUTCOME_COUNT.labels(source).inc()


def setup_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start_time = perf_counter()
        response = await call_next(request)
        latency = perf_counter() - start_time
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(latency)
        REQUEST_COUNT.labels(request.method, request.url.path, str(response.status_code)).inc()
        return response

    @app.get("/metrics", dependencies=[Depends(get_metrics_access)])
    def metrics() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
