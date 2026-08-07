import os
import subprocess
import sys

from fastapi.testclient import TestClient

from src.agent import server
from src.agent.task_queue import TaskQueue
from src.agent.workflow_store import WorkflowStore


ROOT = os.path.dirname(os.path.dirname(__file__))


def test_workflow_store_path_is_read_from_environment(tmp_path):
    path = str(tmp_path / "configured.sqlite3")
    environment = os.environ.copy()
    environment["WORKFLOW_STORE_PATH"] = path

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.agent.config import WORKFLOW_STORE_PATH; print(WORKFLOW_STORE_PATH)",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == path


def test_task_status_route_reads_persisted_workflow(monkeypatch, tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "default", ["echo: first"], 0, 0.0)
    store.complete_workflow("wf-1", ["first"])
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)
    monkeypatch.setattr(server, "get_status", queue.get_status)

    response = TestClient(server.app).get("/api/tasks/wf-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"] == ["first"]


def test_task_status_route_hides_persisted_workflow_from_other_owner(monkeypatch, tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first"], 0, 0.0)
    queue = TaskQueue(worker_count=1, poll_interval=0.01, workflow_store=store)
    monkeypatch.setattr(server, "get_status", queue.get_status)
    monkeypatch.setenv("AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AGENT_API_KEYS", "bob:secret")

    response = TestClient(server.app).get(
        "/api/tasks/wf-1",
        headers={"X-API-Key": "secret"},
    )

    assert response.status_code == 404
