# Durable Agent Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist queued dynamic Agent runs with authenticated encryption and recover them without duplicating uncertain side effects.

**Architecture:** An AES-GCM codec encrypts every user/model/tool content field before SQLite. `AgentRunStore` records runs, decisions, and tool dispatch state; a checkpoint adapter makes the existing AgentRunner durable; TaskQueue recovers idempotent calls and converts interrupted non-idempotent calls to `unknown_outcome`.

**Tech Stack:** Python 3.11, cryptography 50.0.0, AESGCM, SQLite WAL, existing TaskQueue worker threads, asyncio, FastAPI, Prometheus, pytest.

**Primary Reference:** `https://cryptography.io/en/stable/hazmat/primitives/aead/` for AESGCM nonce, associated-data, and authentication behavior.

## Global Constraints

- This plan requires all four preceding plans.
- Pin `cryptography==50.0.0`; do not implement encryption primitives.
- `AGENT_DURABLE_RUNS_ENABLED` defaults to false.
- Enabling durable runs requires `AGENT_RUN_ENCRYPTION_KEY`, URL-safe Base64 encoding of exactly 32 bytes; invalid or missing keys fail startup and never fall back to plaintext.
- Encrypt Prompt, selected Skill IDs, AgentDecision, ToolCall arguments, ToolResult content/error detail, and final answer.
- Use `record-type:run-id:field-name` as AES-GCM associated data and a fresh 12-byte nonce for every encryption.
- Never log the encryption key, plaintext, nonce/ciphertext payload, tool arguments, or decrypted results.
- Interrupted idempotent dispatches may retry; interrupted non-idempotent dispatches become `unknown_outcome` and `needs_attention`.
- Keep fixed WorkflowStore tables and behavior unchanged.

---

## File Map

- Create `src/agent/runtime/crypto.py`, `run_store.py`, `durable_checkpoint.py`, `recovery.py`.
- Modify `src/agent/runtime/models.py`, `runner.py`, `checkpoint.py` for resume state.
- Modify `src/agent/task_queue.py:30-360` for dynamic run work items and one event loop per worker.
- Modify `src/agent/main.py:19-30` for durable enqueue.
- Modify `src/agent/server.py:34-122` for queue/status integration.
- Modify `src/agent/config.py`, `observability.py`, `docker-compose.yml`, `README.md`, `docs/AGENT_GUIDE.md`.
- Modify `requirements.txt` to pin cryptography.
- Create `tests/test_run_crypto.py`, `test_agent_run_store.py`, `test_agent_recovery.py`, `test_durable_agent_queue.py`.
- Modify `tests/test_server.py`, `test_deployment_config.py`.

### Task 1: Add authenticated content encryption

**Files:**
- Create: `src/agent/runtime/crypto.py`
- Modify: `requirements.txt`
- Modify: `src/agent/config.py`
- Test: `tests/test_run_crypto.py`

**Interfaces:**
- Produces: `EncryptedValueCodec.from_base64_key(value)`, `encrypt_json(value, aad) -> bytes`, `decrypt_json(token, aad) -> Any`, `load_run_encryption_codec()`, `EncryptionConfigurationError`, and `EncryptedValueError`.

- [ ] **Step 1: Write failing encryption tests**

```python
import base64
import os
import pytest


def test_encrypted_json_is_not_plaintext_and_round_trips():
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    codec = EncryptedValueCodec.from_base64_key(key)
    token = codec.encrypt_json({"secret": "do-not-store"}, b"decision:run-1:payload")
    assert b"do-not-store" not in token
    assert codec.decrypt_json(token, b"decision:run-1:payload") == {"secret": "do-not-store"}


def test_ciphertext_cannot_move_between_fields():
    codec = codec_fixture()
    token = codec.encrypt_json("secret", b"run:run-1:prompt")
    with pytest.raises(EncryptedValueError):
        codec.decrypt_json(token, b"run:run-1:final_answer")
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_run_crypto.py -q`

Expected: FAIL because the codec is missing.

- [ ] **Step 3: Pin cryptography and implement AES-GCM envelope**

Add `cryptography==50.0.0`. Decode with `base64.b64decode(value, altchars=b"-_", validate=True)`, require exactly 32 bytes, and use this envelope:

```python
class EncryptedValueCodec:
    VERSION = b"\x01"

    def encrypt_json(self, value, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, aad)
        return self.VERSION + nonce + ciphertext
```

`decrypt_json` verifies the version, minimum envelope length, AEAD tag, UTF-8, and JSON. Convert every failure to `EncryptedValueError("invalid_encrypted_value")` without including token/key material.

- [ ] **Step 4: Cover missing, malformed, wrong-length, wrong-key, tampered, and wrong-AAD cases**

```python
@pytest.mark.parametrize("value", ["", "not-base64", base64.urlsafe_b64encode(b"short").decode()])
def test_invalid_keys_are_rejected(value):
    with pytest.raises(EncryptionConfigurationError, match="invalid_run_encryption_key"):
        EncryptedValueCodec.from_base64_key(value)


def test_tampering_is_rejected(codec):
    token = bytearray(codec.encrypt_json("secret", b"run:1:prompt"))
    token[-1] ^= 1
    with pytest.raises(EncryptedValueError, match="invalid_encrypted_value"):
        codec.decrypt_json(bytes(token), b"run:1:prompt")
```

Add `test_wrong_key_is_rejected` and `test_wrong_aad_is_rejected`; both assert the same sanitized error code.

Run: `python -m pytest tests/test_run_crypto.py -q`

Expected: PASS.

- [ ] **Step 5: Commit encryption**

```powershell
git add requirements.txt src/agent/config.py src/agent/runtime/crypto.py tests/test_run_crypto.py
git commit -m "feat: encrypt durable agent content"
```

### Task 2: Persist Agent runs, decisions, and calls

**Files:**
- Create: `src/agent/runtime/run_store.py`
- Test: `tests/test_agent_run_store.py`

**Interfaces:**
- Consumes: `EncryptedValueCodec`, runtime models.
- Produces: `AgentRunStore.create_run`, `save_decision`, `start_tool_call`, `complete_tool_call`, `finish_run`, `get_run`, `list_runs`.

- [ ] **Step 1: Write failing encrypted round-trip test**

```python
def test_store_round_trip_contains_no_plaintext(tmp_path, codec):
    path = tmp_path / "runs.sqlite3"
    store = AgentRunStore(str(path), codec)
    store.create_run("run-1", "alice", "top secret prompt", ["demo.review"], AgentLimits())
    store.save_decision("run-1", 1, FinalDecision(answer="secret answer"))

    raw = b"".join(item.read_bytes() for item in tmp_path.glob("runs.sqlite3*"))
    assert b"top secret prompt" not in raw
    assert b"secret answer" not in raw
    assert store.get_run("run-1", owner_id="alice")["prompt"] == "top secret prompt"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_agent_run_store.py -q`

Expected: FAIL because `AgentRunStore` is missing.

- [ ] **Step 3: Create exact SQLite schema and atomic methods**

Create tables `agent_runs`, `agent_decisions`, and `agent_tool_calls`. Use `(run_id, call_id)` as the tool-call primary key and foreign keys with cascade delete. Store encrypted values in BLOB columns; keep owner, status, round, tool full name, retry flags, and timestamps as queryable metadata.

Every state transition and its event row must commit in one `with self._connection` transaction. `get_run(run_id, owner_id: str | None = None)` must enforce owner isolation in SQL before decrypting.

- [ ] **Step 4: Test reopen, atomicity, owner isolation, duplicate IDs, and ciphertext tampering**

```python
def test_owner_filter_happens_before_decryption(tmp_path, codec, monkeypatch):
    store = AgentRunStore(str(tmp_path / "runs.sqlite3"), codec)
    store.create_run("run-1", "alice", "secret", [], AgentLimits())
    monkeypatch.setattr(codec, "decrypt_json", lambda *args: pytest.fail("must not decrypt"))
    assert store.get_run("run-1", owner_id="bob") is None


def test_duplicate_call_id_is_scoped_by_run(store):
    seed_run(store, "one")
    seed_run(store, "two")
    store.start_tool_call("one", 1, call("same"), idempotent=True)
    store.start_tool_call("two", 1, call("same"), idempotent=True)
    assert store.get_run("one")["tool_calls"][0]["call_id"] == "same"
```

Add reopen, transaction rollback, and ciphertext-tampering tests; scan the main SQLite, WAL, and SHM files for distinctive plaintext.

Run: `python -m pytest tests/test_agent_run_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the encrypted store**

```powershell
git add src/agent/runtime/run_store.py tests/test_agent_run_store.py
git commit -m "feat: persist encrypted agent runs"
```

### Task 3: Connect checkpointing and recovery semantics

**Files:**
- Create: `src/agent/runtime/durable_checkpoint.py`
- Create: `src/agent/runtime/recovery.py`
- Modify: `src/agent/runtime/checkpoint.py`
- Modify: `src/agent/runtime/models.py`
- Modify: `src/agent/runtime/runner.py`
- Test: `tests/test_agent_recovery.py`

**Interfaces:**
- Consumes: AgentRunner checkpoint hooks and AgentRunStore.
- Produces: `SQLiteRunCheckpoint`, `AgentResumeState`, `recover_interrupted_runs(store)`, and `AgentRunner.resume(state)`.

- [ ] **Step 1: Write failing crash-state tests**

```python
def test_recovery_retries_only_interrupted_idempotent_calls(store):
    seed_dispatching_call(store, run_id="safe", idempotent=True)
    seed_dispatching_call(store, run_id="unsafe", idempotent=False)
    summary = recover_interrupted_runs(store)
    assert summary.retryable_run_ids == ["safe"]
    assert store.get_run("unsafe")["status"] == "needs_attention"
    assert store.get_run("unsafe")["tool_calls"][0]["status"] == "unknown_outcome"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_agent_recovery.py -q`

Expected: FAIL because recovery components are missing.

- [ ] **Step 3: Implement durable hooks and resume state**

`SQLiteRunCheckpoint.tool_dispatching()` inserts the call before invocation; `tool_finished()` stores the result immediately. `AgentResumeState` contains decrypted request, selected Skills, completed observations, round count, tool-call count, and at most one interrupted idempotent call to retry before the next model decision.

`AgentRunner.resume()` first executes the stored retryable call using its original call ID and arguments, checkpoints the result, then continues the normal loop. It never re-executes completed calls.

- [ ] **Step 4: Simulate crashes at all three boundaries**

```python
@pytest.mark.anyio
async def test_completed_result_is_not_called_again_after_resume(store, runner, registry):
    state = seed_run_with_completed_tool_result(store, result={"value": 1})
    outcome = await runner.resume(state)
    assert registry.calls == []
    assert outcome.status == "completed"


def test_interrupted_non_idempotent_call_never_requeues(store):
    seed_dispatching_call(store, run_id="unsafe", idempotent=False)
    summary = recover_interrupted_runs(store)
    assert "unsafe" not in summary.retryable_run_ids
    assert store.get_run("unsafe")["status"] == "needs_attention"
```

Also simulate a crash before the dispatch record and after result persistence; assert zero duplicate invocations in both cases.

Run: `python -m pytest tests/test_agent_recovery.py tests/test_agent_runner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit durable recovery**

```powershell
git add src/agent/runtime tests/test_agent_recovery.py tests/test_agent_runner.py
git commit -m "feat: recover agent runs safely"
```

### Task 4: Queue and recover dynamic runs

**Files:**
- Modify: `src/agent/task_queue.py:30-360`
- Modify: `src/agent/main.py:19-30`
- Test: `tests/test_durable_agent_queue.py`

**Interfaces:**
- Consumes: `AgentRunStore`, `AgentRunner.resume`.
- Produces: `TaskQueue.configure_agent_runs`, `enqueue_agent_run`, and startup recovery.

- [ ] **Step 1: Write failing queue recovery test**

```python
def test_queue_recovers_persisted_agent_run_after_restart(tmp_path, durable_runtime):
    first = durable_runtime.new_queue()
    run_id = durable_runtime.create_pending_run("alice", "search")
    first.stop()

    second = durable_runtime.new_queue()
    second.start()
    wait_until(lambda: durable_runtime.store.get_run(run_id)["status"] == "completed")
    assert durable_runtime.fake_llm.call_count == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_durable_agent_queue.py -q`

Expected: FAIL because TaskQueue cannot enqueue Agent runs.

- [ ] **Step 3: Add an `agent_run` queue item and one loop per worker**

Create one asyncio event loop at the start of each `_worker_loop` thread and close it when that worker exits. For `agent_run` items call `loop.run_until_complete(agent_run_executor(run_id))`; do not call `asyncio.run()` per task.

On queue startup, call `recover_interrupted_runs`, enqueue pending/retryable run IDs, and leave `needs_attention` runs unqueued.

- [ ] **Step 4: Test deduplication, shutdown, retry, and coexistence with fixed workflows**

```python
def test_enqueue_agent_run_is_deduplicated(queue, run_store):
    seed_pending_run(run_store, "run-1")
    queue.enqueue_agent_run("run-1")
    queue.enqueue_agent_run("run-1")
    assert queue.queued_agent_run_ids() == {"run-1"}


def test_fixed_workflow_and_agent_run_share_worker_without_type_confusion(queue, fixtures):
    workflow_id = fixtures.enqueue_workflow(queue)
    run_id = fixtures.enqueue_agent_run(queue)
    queue.start()
    fixtures.wait_for_terminal(workflow_id, run_id)
    assert fixtures.workflow_store.get_workflow(workflow_id)["status"] == "completed"
    assert fixtures.run_store.get_run(run_id)["status"] == "completed"
```

Add shutdown cleanup and idempotent-retry tests; assert each worker loop is closed once and no retry timer is left running.

Run: `python -m pytest tests/test_durable_agent_queue.py tests/test_task_queue.py tests/test_persistent_task_queue.py tests/test_persistent_executor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit queue support**

```powershell
git add src/agent/task_queue.py src/agent/main.py tests/test_durable_agent_queue.py
git commit -m "feat: queue durable agent runs"
```

### Task 5: Wire API, status, metrics, and deployment controls

**Files:**
- Modify: `src/agent/server.py:34-122`
- Modify: `src/agent/config.py`
- Modify: `src/agent/observability.py`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `docs/AGENT_GUIDE.md`
- Modify: `tests/test_server.py`
- Modify: `tests/test_deployment_config.py`

**Interfaces:**
- Consumes: configured AgentRunStore and TaskQueue.
- Produces: durable `/api/handle/queue`, owner-scoped task status, and final operational documentation.

- [ ] **Step 1: Write failing startup and API tests**

```python
def test_durable_runtime_refuses_missing_encryption_key(monkeypatch):
    monkeypatch.setenv("AGENT_DURABLE_RUNS_ENABLED", "true")
    monkeypatch.delenv("AGENT_RUN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AGENT_RUN_ENCRYPTION_KEY"):
        with TestClient(server.app):
            pass


def test_queued_agent_status_is_owner_scoped(authenticated_clients, durable_app):
    run_id = authenticated_clients.alice.post("/api/handle/queue", json={"prompt": "search"}).json()["task_id"]
    assert authenticated_clients.bob.get(f"/api/tasks/{run_id}").status_code == 404
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m pytest tests/test_server.py tests/test_deployment_config.py -q`

Expected: FAIL because durable startup and status routing are absent.

- [ ] **Step 3: Configure durable state only when enabled**

During lifespan, load the codec first, then construct `AgentRunStore` against the same `WORKFLOW_STORE_PATH` SQLite file, configure TaskQueue, and start recovery. If durable runs are disabled, do not read or validate the encryption key.

`/api/handle/queue` uses dynamic Agent runs only when both capability and durable flags are true; otherwise it preserves the legacy queue behavior. Add `run_type` to task status without removing existing fields.

- [ ] **Step 4: Add bounded metrics and deployment documentation**

Add run rounds, budget exhaustion, and unknown outcome counters with bounded labels. Forward these Compose variables without defaults containing secrets:

```yaml
- AGENT_DURABLE_RUNS_ENABLED=${AGENT_DURABLE_RUNS_ENABLED:-false}
- AGENT_RUN_ENCRYPTION_KEY=${AGENT_RUN_ENCRYPTION_KEY:-}
```

Document key generation with `base64.urlsafe_b64encode(os.urandom(32))`, backup/restore requirements, and that losing the key makes encrypted run content unrecoverable. Never print an existing key in diagnostics.

```python
def test_compose_forwards_durable_flags_without_a_default_secret():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "AGENT_DURABLE_RUNS_ENABLED=${AGENT_DURABLE_RUNS_ENABLED:-false}" in compose
    assert "AGENT_RUN_ENCRYPTION_KEY=${AGENT_RUN_ENCRYPTION_KEY:-}" in compose
    assert "AGENT_RUN_ENCRYPTION_KEY=" not in compose.replace(
        "AGENT_RUN_ENCRYPTION_KEY=${AGENT_RUN_ENCRYPTION_KEY:-}", ""
    )
```

- [ ] **Step 5: Run full verification and commit**

Run: `python -m pytest tests/test_server.py tests/test_deployment_config.py tests/test_agent_run_store.py tests/test_agent_recovery.py tests/test_durable_agent_queue.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: all tests PASS.

```powershell
git add src/agent/server.py src/agent/config.py src/agent/observability.py docker-compose.yml README.md docs/AGENT_GUIDE.md tests/test_server.py tests/test_deployment_config.py
git commit -m "feat: operate durable encrypted agent runs"
```

## Plan Completion Gate

Run:

```powershell
python -m pip check
python -m pytest -q
git diff --check
```

Then create a temporary encrypted run with distinctive plaintext, stop the service between dispatch and result in the controlled test harness, restart, and verify:

- the SQLite file does not contain the distinctive plaintext;
- an idempotent call resumes once;
- a non-idempotent call becomes `needs_attention` with `unknown_outcome`;
- owner isolation remains enforced;
- the encryption key never appears in captured logs.
