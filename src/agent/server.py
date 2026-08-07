import logging
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from src.agent.main import handle_input, enqueue_input
from src.agent.memory_manager import initialize_memory, save_memory
from src.agent.observability import setup_metrics
from src.agent.security import audit_log, sanitize_input
from src.agent.task_queue import get_status, list_tasks, start_queue, stop_queue
from src.agent.tool_registry import list_tool_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI()
setup_metrics(app)


class PromptIn(BaseModel):
    prompt: str


class TaskStatusOut(BaseModel):
    task_id: str
    status: str
    attempts: int
    max_retries: int
    retry_delay: float
    result: Optional[Any] = None
    error: str = ""
    created_at: float
    completed_at: Optional[float] = None


@app.on_event("startup")
def on_startup():
    initialize_memory()
    start_queue()


@app.on_event("shutdown")
def on_shutdown():
    save_memory()
    stop_queue()


@app.get("/")
def root():
    return {"status": "ok", "message": "Minimal Agent is running"}


@app.post("/api/handle")
def handle_route(payload: PromptIn):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log("anonymous", "request_received", safe_prompt)
    result = handle_input(safe_prompt)
    audit_log("anonymous", "request_completed", result)
    return {"result": result}


@app.post("/api/handle/queue")
def handle_queue_route(payload: PromptIn):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log("anonymous", "request_queued", safe_prompt)
    status = enqueue_input(safe_prompt)
    audit_log("anonymous", "request_queued_completed", status)
    return status


@app.get("/api/tasks/{task_id}")
def get_task_route(task_id: str):
    record = get_status(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusOut(**record.__dict__)


@app.get("/api/tasks")
def list_tasks_route(status: Optional[str] = None):
    records = list_tasks(status)
    return [TaskStatusOut(**record.__dict__) for record in records]


class ToolInfoOut(BaseModel):
    name: str
    description: str = ""


@app.get("/api/tools")
def list_tools_route():
    tools = list_tool_metadata()
    return [ToolInfoOut(**tool) for tool in tools]
