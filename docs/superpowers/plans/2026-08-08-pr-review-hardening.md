# PR Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four actionable review findings on PR #2 without weakening SSRF protection, metrics authentication, or vector-memory consistency.

**Architecture:** Keep the existing HTTP pinning context, but normalize DNS names at its boundary and serialize the patch/snapshot/restore lifecycle under the existing lock. Keep Prometheus bearer-file authentication and make only the YAML nesting change. Make `VectorStore.add` commit all three parallel collections only after embedding succeeds.

**Tech Stack:** Python 3, pytest, Requests, Prometheus YAML configuration, Docker Compose, GitHub Actions.

## Global Constraints

- Preserve the original hostname in the URL so Requests retains normal TLS and `Host` behavior.
- Do not add a new dependency for IDNA; use Python's built-in codec.
- Preserve the existing `_DNS_PIN_LOCK` lifecycle and serialize the whole temporary resolver context.
- Keep Prometheus bearer authentication enabled through `/etc/prometheus/data/metrics-token`.
- An embedding exception must propagate and leave documents, metadata, and vectors unchanged.
- Resolve GitHub threads only after local tests, remote CI, and thread-aware state are verified.

---

### Task 1: Normalize DNS hostnames for validation and pinning

**Files:**
- Modify: `src/agent/http_security.py:22-115`
- Test: `tests/test_http_tool.py`

**Interfaces:**
- Produce `_normalize_hostname(hostname: str) -> str` for internal allowlist and resolver matching.
- Preserve `ParsedURL.hostname` as the lowercased URL hostname; compare its normalized form only at DNS boundaries.

- [ ] **Step 1: Write the failing tests**

Update the import and add these tests to `tests/test_http_tool.py`:

```python
from src.agent.http_security import ParsedURL, pin_dns_resolution, validate_http_url
```

```python
def test_validate_http_url_accepts_unicode_host_against_idna_allowlist(monkeypatch):
    monkeypatch.setenv("AGENT_HTTP_ALLOWED_HOSTS", "xn--bcher-kva.example")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    parsed = validate_http_url("https://bücher.example/data")

    assert parsed.hostname == "bücher.example"


def test_pinned_dns_matches_idna_connection_hostname(monkeypatch):
    parsed = ParsedURL(
        url="https://bücher.example/data",
        scheme="https",
        hostname="bücher.example",
        port=443,
        resolved_addresses=("93.184.216.34",),
    )

    def unexpected_resolution(*args, **kwargs):
        raise AssertionError("validated hostname was not used")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_resolution)
    with pin_dns_resolution(parsed):
        pinned = socket.getaddrinfo("xn--bcher-kva.example", 443, type=socket.SOCK_STREAM)

    assert pinned[0][4][0] == "93.184.216.34"
    assert socket.getaddrinfo is unexpected_resolution
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest -q tests/test_http_tool.py -k "unicode or idna"`

Expected: FAIL because the allowlist compares Unicode and IDNA forms directly and the pinned resolver compares raw host strings.

- [ ] **Step 3: Implement the minimal normalization**

In `src/agent/http_security.py`, add:

```python
def _normalize_hostname(hostname: str) -> str:
    return hostname.rstrip(".").lower().encode("idna").decode("ascii")
```

Use it for both configured hosts and the validated hostname used in allowlist comparison. Use it again inside `pin_dns_resolution` for the requested host comparison. Keep `ParsedURL.hostname` and `ParsedURL.url` unchanged apart from their existing lowercase behavior.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest -q tests/test_http_tool.py -k "unicode or idna"`

Expected: PASS.

- [ ] **Step 5: Commit the focused fix**

```bash
git add tests/test_http_tool.py src/agent/http_security.py
git commit -m "fix: normalize IDNA hostnames for DNS pinning"
```

---

### Task 2: Make DNS resolver restoration safe under overlap

**Files:**
- Modify: `src/agent/http_security.py:92-121`
- Test: `tests/test_http_tool.py`

**Interfaces:**
- Keep `pin_dns_resolution(parsed)` as the public context manager.
- The lock must be acquired before reading `socket.getaddrinfo` and held until restoration completes.

- [ ] **Step 1: Write the failing concurrency test**

Add a test that replaces the module lock with an instrumented lock. The first context holds the lock while a second context attempts entry; after both finish, assert the original resolver is restored and neither worker raised:

```python
def test_overlapping_dns_pinning_restores_original_resolver(monkeypatch):
    import threading

    class GateLock:
        def __init__(self):
            self._lock = threading.Lock()
            self.second_attempted = threading.Event()
            self.calls = 0

        def __enter__(self):
            self.calls += 1
            if self.calls == 2:
                self.second_attempted.set()
            self._lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._lock.release()

    import src.agent.http_security as security
    original_resolver = socket.getaddrinfo
    gate = GateLock()
    monkeypatch.setattr(security, "_DNS_PIN_LOCK", gate)
    parsed = ParsedURL(
        url="https://api.example.com/data",
        scheme="https",
        hostname="api.example.com",
        port=443,
        resolved_addresses=("93.184.216.34",),
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    errors = []

    def worker():
        try:
            with pin_dns_resolution(parsed):
                first_entered.set()
                release_first.wait(timeout=2)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    assert gate.second_attempted.wait(timeout=2)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not errors
    assert not first.is_alive()
    assert not second.is_alive()
    assert socket.getaddrinfo is original_resolver
```

- [ ] **Step 2: Run the concurrency test to verify it fails**

Run: `python -m pytest -q tests/test_http_tool.py -k overlapping`

Expected: FAIL on the current implementation because the second context snapshots the first temporary resolver before waiting for the lock.

- [ ] **Step 3: Move the resolver snapshot inside the lock**

Change `pin_dns_resolution` so `with _DNS_PIN_LOCK:` is entered before `original_getaddrinfo = socket.getaddrinfo` and before defining/assigning the temporary resolver. Keep the existing `try/finally` restoration and yield inside the lock.

- [ ] **Step 4: Run HTTP tests**

Run: `python -m pytest -q tests/test_http_tool.py`

Expected: PASS.

- [ ] **Step 5: Commit the focused fix**

```bash
git add tests/test_http_tool.py src/agent/http_security.py
git commit -m "fix: restore DNS resolver safely across concurrent requests"
```

---

### Task 3: Correct Prometheus scrape authorization nesting

**Files:**
- Modify: `prometheus.yml:4-10`
- Test: `tests/test_deployment_config.py:6-18`

**Interfaces:**
- Keep the existing bearer token file path and Compose mount.
- Place `authorization` directly below the `minimal-agent` scrape job, with no `http_config` wrapper.

- [ ] **Step 1: Strengthen the failing configuration test**

Extend `test_prometheus_config_is_tracked_and_compose_references_it` with:

```python
    assert "    authorization:" in prometheus
    assert "    http_config:" not in prometheus
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest -q tests/test_deployment_config.py::test_prometheus_config_is_tracked_and_compose_references_it`

Expected: FAIL because the current file contains `http_config`.

- [ ] **Step 3: Flatten the YAML field**

Change `prometheus.yml` to:

```yaml
  - job_name: minimal-agent
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/data/metrics-token
```

- [ ] **Step 4: Run config validation**

Run: `python -m pytest -q tests/test_deployment_config.py::test_prometheus_config_is_tracked_and_compose_references_it`

Expected: PASS.

- [ ] **Step 5: Commit the focused fix**

```bash
git add tests/test_deployment_config.py prometheus.yml
git commit -m "fix: use supported Prometheus scrape authorization"
```

---

### Task 4: Make vector additions transactional on embedding failure

**Files:**
- Modify: `src/agent/vector_store.py:17-25`
- Create: `tests/test_vector_store.py`

**Interfaces:**
- Keep `VectorStore.add(text, metadata)` unchanged.
- The adapter's `embed(text)` call happens before any of the three parallel collections are mutated.

- [ ] **Step 1: Write the failing regression test**

Create `tests/test_vector_store.py`:

```python
import json

import pytest

from src.agent.embeddings import EmbeddingAdapter
from src.agent.vector_store import VectorStore


class FailsOnSecondEmbedding(EmbeddingAdapter):
    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("embedding unavailable")
        return [float(self.calls)]


def test_failed_embedding_does_not_partially_append_vector_record(tmp_path):
    store = VectorStore(FailsOnSecondEmbedding())
    path = tmp_path / "vectors.json"

    store.add("first", {"user_id": "u1"})
    store.save(str(path))
    baseline = json.loads(path.read_text(encoding="utf-8"))

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        store.add("second", {"user_id": "u1"})

    store.save(str(path))
    assert json.loads(path.read_text(encoding="utf-8")) == baseline
```

- [ ] **Step 2: Run the regression test to verify it fails**

Run: `python -m pytest -q tests/test_vector_store.py::test_failed_embedding_does_not_partially_append_vector_record`

Expected: FAIL because the current implementation appends the document and metadata before calling `embed`.

- [ ] **Step 3: Implement the transactional append**

Change `VectorStore.add` to:

```python
    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        with self._lock:
            vector = self._adapter.embed(text)
            self._documents.append(text)
            self._metadata.append(metadata or {})
            self._vectors.append(vector)
```

- [ ] **Step 4: Run vector-store tests**

Run: `python -m pytest -q tests/test_vector_store.py tests/test_vector_memory.py`

Expected: PASS.

- [ ] **Step 5: Commit the focused fix**

```bash
git add tests/test_vector_store.py src/agent/vector_store.py
git commit -m "fix: keep vector store additions atomic"
```

---

### Task 5: Full verification, push, and resolve only the four fixed threads

**Files:**
- Verify: all changed files and current worktree

- [ ] **Step 1: Run the complete local verification**

Run:

```powershell
python -m pytest -q
python -m compileall -q src tests
docker compose config
git diff --check
git status --short --branch
```

Expected: all tests pass, Compose prints a normalized configuration, no whitespace errors, and only intended commits are present.

- [ ] **Step 2: Push the branch**

```bash
git push origin codex/agent-hardening
```

- [ ] **Step 3: Verify GitHub Actions and review state**

Use `gh pr checks 2 --repo qq550723504/minimal-agent` and the thread-aware `fetch_comments.py` script. Confirm the new head's `test` check succeeds and only the four known review threads remain unresolved.

- [ ] **Step 4: Resolve the four addressed threads**

Use GraphQL `resolveReviewThread` only for:

```text
PRRT_kwDOTw3oXc6XUYGX
PRRT_kwDOTw3oXc6XUYGe
PRRT_kwDOTw3oXc6XUYGl
PRRT_kwDOTw3oXc6XUYGs
```

- [ ] **Step 5: Recheck the final PR state**

Confirm all review threads are resolved, CI is green, the worktree is clean, and PR #2 is no longer blocked by conversation resolution.
