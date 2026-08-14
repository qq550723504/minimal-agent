import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.agent.application.requests import enqueue_input, handle_input_async
from src.agent.infrastructure.workflows.task_queue import get_status, list_tasks
from src.agent.security.auth import get_current_user
from src.agent.security.input import audit_log, sanitize_input

from ..schemas import PromptIn, TaskStatusOut

router = APIRouter()


def _app_module():
    from src.agent.api import app

    return app


def _sse_event(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/api/handle")
async def handle_route(
    payload: PromptIn,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log(user_id, "request_received", safe_prompt)
    if payload.response_mode == "structured":
        result = await _app_module().handle_input_structured_async(
            safe_prompt,
            user_id=user_id,
            skill_catalog=request.app.state.skill_catalog,
        )
        audit_log(user_id, "request_completed", result)
        return result
    result = await _app_module().handle_input_async(
        safe_prompt,
        user_id=user_id,
        skill_catalog=request.app.state.skill_catalog,
    )
    audit_log(user_id, "request_completed", result)
    return {"result": result}


@router.post("/api/handle/stream")
async def handle_stream_route(
    payload: PromptIn,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log(user_id, "request_received", safe_prompt)

    async def event_stream():
        try:
            final_result = None
            async for event in _app_module().stream_input_structured_async(
                safe_prompt,
                user_id=user_id,
                skill_catalog=request.app.state.skill_catalog,
            ):
                if event.get("event") == "result":
                    final_result = event.get("data")
                yield _sse_event(event["event"], event.get("data", {}))
            if final_result is not None:
                audit_log(user_id, "request_completed", final_result)
        except Exception as exc:
            audit_log(user_id, "request_failed", str(exc))
            yield _sse_event(
                "error",
                {"message": "Agent 流式处理失败，请检查服务状态。", "error_code": "stream_failed"},
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/handle/queue")
def handle_queue_route(
    payload: PromptIn,
    user_id: str = Depends(get_current_user),
):
    safe_prompt = sanitize_input(payload.prompt)
    audit_log(user_id, "request_queued", safe_prompt)
    status = _app_module().enqueue_input(safe_prompt, user_id=user_id)
    audit_log(user_id, "request_queued_completed", status)
    return status


@router.get("/api/tasks/{task_id}")
def get_task_route(task_id: str, user_id: str = Depends(get_current_user)):
    record = _app_module().get_status(task_id, owner_id=user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusOut(**record.__dict__)


@router.get("/api/tasks")
def list_tasks_route(status: Optional[str] = None, user_id: str = Depends(get_current_user)):
    records = _app_module().list_tasks(status, owner_id=user_id)
    return [TaskStatusOut(**record.__dict__) for record in records]
