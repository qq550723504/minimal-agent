import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.agent import config
from src.agent.application.requests import (
    enqueue_input,
    handle_input_async,
    handle_input_structured_async,
    stream_input_structured_async,
)
from src.agent.domain.capabilities.models import ToolSource
from src.agent.infrastructure.mcp.manager import MCPClientManager
from src.agent.infrastructure.memory.memory_manager import initialize_memory, save_memory
from src.agent.infrastructure.plugins.catalog import PluginCatalog
from src.agent.infrastructure.plugins.loader import PluginLoader
from src.agent.infrastructure.skills.loader import SkillCatalog
from src.agent.infrastructure.skills.reference_tool import register_skill_reference_tool
from src.agent.infrastructure.workflows.task_queue import get_status, list_tasks, start_queue, stop_queue
from src.agent.observability import record_catalog_startup, setup_metrics
from src.agent.security.input import ClientInputError
from src.agent.tool_registry import get_capability_registry
from src.agent.version import __version__

from .routes.catalog import router as catalog_router
from .routes.docs import router as docs_router
from .routes.handle import router as handle_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_CAPABILITY_RUNTIME_TOOL_NAMES = ("internal.skill_read_reference",)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own the capability runtime and its MCP transports for one app lifetime."""
    manager = MCPClientManager()
    initialize_memory()
    try:
        _clear_capability_runtime()
        if config.CAPABILITY_RUNTIME_ENABLED:
            plugin_catalog = PluginLoader(Path(config.PLUGIN_DIR)).load_all()
            await manager.start_catalog(plugin_catalog, get_capability_registry())
            skill_catalog = SkillCatalog.from_plugins(plugin_catalog)
            register_skill_reference_tool(get_capability_registry(), skill_catalog)
        else:
            plugin_catalog = PluginCatalog()
            skill_catalog = SkillCatalog()

        application.state.plugin_catalog = plugin_catalog
        application.state.skill_catalog = skill_catalog
        application.state.mcp_manager = manager
        record_catalog_startup(plugin_catalog, len(manager.server_ids()))
        start_queue()
        yield
    finally:
        cleanup_errors: list[RuntimeError] = []
        try:
            stop_queue()
        except Exception:
            cleanup_errors.append(RuntimeError("queue_cleanup_failed"))
        try:
            await manager.close()
        except Exception:
            cleanup_errors.append(RuntimeError("mcp_cleanup_failed"))
        try:
            _clear_capability_runtime()
        except Exception:
            cleanup_errors.append(RuntimeError("capability_runtime_cleanup_failed"))
        try:
            save_memory()
        except Exception:
            cleanup_errors.append(RuntimeError("memory_cleanup_failed"))

        if cleanup_errors:
            cleanup_failure = ExceptionGroup("lifespan_cleanup_failed", cleanup_errors)
            if sys.exception() is None:
                raise cleanup_failure
            logging.error("Agent lifecycle cleanup failed: %s", cleanup_failure)


app = FastAPI(
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.state.plugin_catalog = PluginCatalog()
app.state.skill_catalog = SkillCatalog()
app.state.mcp_manager = None
setup_metrics(app)

_SECURITY_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "demos" / "park-security"
if _SECURITY_DASHBOARD_DIR.is_dir():
    for dashboard_route, dashboard_name in (
        ("/park-agent", "park_agent_dashboard"),
        ("/security", "security_dashboard_legacy"),
    ):
        app.mount(
            dashboard_route,
            StaticFiles(directory=_SECURITY_DASHBOARD_DIR, html=True),
            name=dashboard_name,
        )


@app.exception_handler(ClientInputError)
async def client_input_error_handler(_request, exc: ClientInputError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _clear_capability_runtime() -> None:
    registry = get_capability_registry()
    for tool_name in _CAPABILITY_RUNTIME_TOOL_NAMES:
        registry.unregister(tool_name)
    for spec in registry.list_specs():
        if spec.source is ToolSource.MCP:
            registry.unregister(spec.name)
    app.state.plugin_catalog = PluginCatalog()
    app.state.skill_catalog = SkillCatalog()
    app.state.mcp_manager = None


@app.get("/")
def root():
    return {"status": "ok", "message": "Minimal Agent is running"}


app.include_router(docs_router)
app.include_router(handle_router)
app.include_router(catalog_router)
