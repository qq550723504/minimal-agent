import logging

from fastapi import FastAPI
from pydantic import BaseModel
from src.agent.main import handle_input
from src.agent.observability import setup_metrics
from src.agent.security import audit_log, sanitize_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI()
setup_metrics(app)


class PromptIn(BaseModel):
    prompt: str


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
