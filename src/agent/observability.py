from time import perf_counter

from fastapi import Depends, FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from src.agent.auth import get_current_user

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


def setup_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start_time = perf_counter()
        response = await call_next(request)
        latency = perf_counter() - start_time
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(latency)
        REQUEST_COUNT.labels(request.method, request.url.path, str(response.status_code)).inc()
        return response

    @app.get("/metrics", dependencies=[Depends(get_current_user)])
    def metrics() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
