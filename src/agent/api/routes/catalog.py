from fastapi import APIRouter, Depends, Request

from src.agent.domain.capabilities.models import ToolSource
from src.agent.infrastructure.plugins.catalog import PluginCatalog, PluginStatus
from src.agent.infrastructure.skills.loader import SkillCatalog
from src.agent.security.auth import get_current_user
from src.agent.tool_registry import get_capability_registry, list_tool_metadata

from ..schemas import PluginCatalogOut, SkillCatalogOut, ToolInfoOut

router = APIRouter()


@router.get("/api/tools")
def list_tools_route(_user_id: str = Depends(get_current_user)):
    tools = list_tool_metadata()
    return [ToolInfoOut(**tool) for tool in tools]


@router.get("/api/plugins")
def list_plugins_route(request: Request, _user_id: str = Depends(get_current_user)):
    catalog: PluginCatalog = request.app.state.plugin_catalog
    return [_plugin_catalog_out(catalog, status) for status in catalog.statuses.values()]


@router.get("/api/skills")
def list_skills_route(request: Request, _user_id: str = Depends(get_current_user)):
    catalog: SkillCatalog = request.app.state.skill_catalog
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
