from src.agent.workflow_store import WorkflowStore


def test_workflow_round_trip_survives_reopen(tmp_path):
    path = tmp_path / "workflows.sqlite3"
    store = WorkflowStore(str(path))
    store.create_workflow(
        "wf-1",
        "alice",
        ["echo: first", {"tool": "echo", "payload": "second"}],
        2,
        0.25,
    )

    reopened = WorkflowStore(str(path))
    record = reopened.get_workflow("wf-1", owner_id="alice")

    assert record["workflow_id"] == "wf-1"
    assert record["owner_id"] == "alice"
    assert record["status"] == "pending"
    assert record["max_retries"] == 2
    assert record["retry_delay"] == 0.25
    assert [step["definition"] for step in record["steps"]] == [
        "echo: first",
        {"tool": "echo", "payload": "second"},
    ]
    assert [step["status"] for step in record["steps"]] == ["pending", "pending"]


def test_workflow_reads_are_owner_isolated(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first"], 0, 0.0)

    assert store.get_workflow("wf-1", owner_id="bob") is None
    assert store.list_workflows(owner_id="bob") == []
    assert [item["workflow_id"] for item in store.list_workflows(owner_id="alice")] == ["wf-1"]


def test_step_completion_persists_result_and_event_atomically(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first", "echo: second"], 0, 0.0)

    store.start_workflow("wf-1")
    store.start_step("wf-1", 0)
    store.complete_step("wf-1", 0, "first result", ["first result"])

    record = store.get_workflow("wf-1", owner_id="alice")
    assert record["status"] == "running"
    assert record["results"] == ["first result"]
    assert record["steps"][0]["status"] == "completed"
    assert record["steps"][0]["result"] == "first result"
    assert any(
        event["event_type"] == "step_completed" and event["step_index"] == 0
        for event in record["events"]
    )


def test_workflow_recovery_and_terminal_lifecycle_are_persisted(tmp_path):
    store = WorkflowStore(str(tmp_path / "workflows.sqlite3"))
    store.create_workflow("wf-1", "alice", ["echo: first"], 1, 0.1)
    store.create_workflow("wf-2", "alice", ["echo: second"], 0, 0.0)

    store.start_workflow("wf-1")
    store.start_workflow("wf-2")
    assert store.mark_interrupted_workflows_pending() == 2
    assert store.list_recoverable_workflows() == ["wf-1", "wf-2"]

    store.retry_workflow("wf-1", "temporary failure", 0)
    retry_record = store.get_workflow("wf-1", owner_id="alice")
    assert retry_record["status"] == "retrying"
    assert retry_record["failed_step"] == 0

    store.fail_workflow("wf-1", "permanent failure", 0, [])
    failed_record = store.get_workflow("wf-1", owner_id="alice")
    assert failed_record["status"] == "failed"
    assert failed_record["error"] == "permanent failure"

    store.complete_workflow("wf-2", ["second result"])
    completed_record = store.get_workflow("wf-2", owner_id="alice")
    assert completed_record["status"] == "completed"
    assert completed_record["results"] == ["second result"]
    assert completed_record["completed_at"] is not None
