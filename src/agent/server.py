import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from src.agent import config
from src.agent.security.auth import get_current_user
from src.agent.main import enqueue_input, handle_input_async
from src.agent.memory_manager import initialize_memory, save_memory
from src.agent.domain.capabilities.models import ToolSource
from src.agent.mcp.manager import MCPClientManager
from src.agent.observability import record_catalog_startup, setup_metrics
from src.agent.plugins.catalog import PluginCatalog, PluginStatus
from src.agent.plugins.loader import PluginLoader
from src.agent.security.input import ClientInputError, audit_log, sanitize_input
from src.agent.skills.loader import SkillCatalog
from src.agent.skills.reference_tool import register_skill_reference_tool
from src.agent.task_queue import get_status, list_tasks, start_queue, stop_queue
from src.agent.tool_registry import get_capability_registry, list_tool_metadata
from src.agent.version import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_CAPABILITY_RUNTIME_TOOL_NAMES = ("internal.skill_read_reference",)


class PromptIn(BaseModel):
    prompt: str


class TaskStatusOut(BaseModel):
    task_id: str
    owner_id: str
    status: str
    attempts: int
    max_retries: int
    retry_delay: float
    result: Optional[Any] = None
    error: str = ""
    failed_step: Optional[int] = None
    created_at: float
    completed_at: Optional[float] = None


class PluginCatalogOut(BaseModel):
    installation_name: str
    state: str
    plugin_id: Optional[str] = None
    version: Optional[str] = None
    error_code: Optional[str] = None
    capabilities: List[str] = []


class SkillCatalogOut(BaseModel):
    id: str
    plugin_id: str
    triggers: List[str] = []


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


@app.get("/openapi.json", include_in_schema=False)
def openapi_route(_user_id: str = Depends(get_current_user)):
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def docs_route(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    _user_id: str = Depends(get_current_user),
):
    response = get_swagger_ui_html(openapi_url="/openapi.json", title="Minimal Agent - Swagger UI")
    if api_key:
        response.set_cookie("agent_session", api_key, httponly=True, samesite="lax")
    return response


@app.get("/redoc", include_in_schema=False)
def redoc_route(
    api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    _user_id: str = Depends(get_current_user),
):
    response = get_redoc_html(openapi_url="/openapi.json", title="Minimal Agent - ReDoc")
    if api_key:
        response.set_cookie("agent_session", api_key, httponly=True, samesite="lax")
    return response


@app.post("/api/handle")
async def handle_route(payload: PromptIn, user_id: str = Depends(get_current_user)):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log(user_id, "request_received", safe_prompt)
    result = await handle_input_async(
        safe_prompt,
        user_id=user_id,
        skill_catalog=app.state.skill_catalog,
    )
    audit_log(user_id, "request_completed", result)
    return {"result": result}


@app.post("/api/handle/queue")
def handle_queue_route(payload: PromptIn, user_id: str = Depends(get_current_user)):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log(user_id, "request_queued", safe_prompt)
    status = enqueue_input(safe_prompt, user_id=user_id)
    audit_log(user_id, "request_queued_completed", status)
    return status


@app.get("/api/tasks/{task_id}")
def get_task_route(task_id: str, user_id: str = Depends(get_current_user)):
    record = get_status(task_id, owner_id=user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusOut(**record.__dict__)


@app.get("/api/tasks")
def list_tasks_route(status: Optional[str] = None, user_id: str = Depends(get_current_user)):
    records = list_tasks(status, owner_id=user_id)
    return [TaskStatusOut(**record.__dict__) for record in records]


class ToolInfoOut(BaseModel):
    name: str
    description: str = ""
    source: str
    plugin_id: Optional[str] = None
    input_schema: dict[str, Any]
    side_effects: bool
    idempotent: bool


@app.get("/api/tools")
def list_tools_route(_user_id: str = Depends(get_current_user)):
    tools = list_tool_metadata()
    return [ToolInfoOut(**tool) for tool in tools]


@app.get("/api/plugins")
def list_plugins_route(_user_id: str = Depends(get_current_user)):
    catalog: PluginCatalog = app.state.plugin_catalog
    return [_plugin_catalog_out(catalog, status) for status in catalog.statuses.values()]


@app.get("/api/skills")
def list_skills_route(_user_id: str = Depends(get_current_user)):
    catalog: SkillCatalog = app.state.skill_catalog
    return [
        SkillCatalogOut(
            id=skill.id,
            plugin_id=skill.plugin_id,
            triggers=list(skill.triggers),
        )
        for skill in catalog.sorted()
    ]


def _plugin_catalog_out(catalog: PluginCatalog, status: PluginStatus) -> PluginCatalogOut:
    plugin = catalog.plugins.get(status.plugin_id) if status.plugin_id else None
    capabilities = []
    if plugin is not None:
        capabilities = sorted(
            {
                tool.name
                for server in plugin.manifest.mcp_servers
                for tool in server.allowed_tools
            }
        )
    return PluginCatalogOut(
        installation_name=status.installation_name,
        state=status.state,
        plugin_id=status.plugin_id,
        version=status.version,
        error_code=status.error_code,
        capabilities=capabilities,
    )
