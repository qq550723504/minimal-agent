from typing import Any, List, Literal, Optional

from pydantic import BaseModel


class PromptIn(BaseModel):
    prompt: str
    response_mode: Literal["text", "structured"] = "text"


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


class ToolInfoOut(BaseModel):
    name: str
    description: str = ""
    source: str
    plugin_id: Optional[str] = None
    input_schema: dict[str, Any]
    side_effects: bool
    idempotent: bool
