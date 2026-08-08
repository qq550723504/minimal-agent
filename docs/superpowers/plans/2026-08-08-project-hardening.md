# Project Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the container, production configuration, dependency boundary, release metadata, and CI without changing provider interfaces or single-process workflow semantics.

**Architecture:** Keep the existing FastAPI/config/Compose structure. Add production validation to `src/agent/config.py`, use a development base Compose file plus a required-variable production override, and keep the Docker image limited to runtime source and dependencies. Treat the SQLite/in-process queue as an explicit single-instance boundary.

**Tech Stack:** Python 3.11, FastAPI, pytest, Dockerfile, Docker Compose, GitHub Actions.

## Global Constraints

- Preserve development defaults: mock providers and `AGENT_AUTH_REQUIRED=false`.
- Production requires authentication, non-default API keys, a non-default metrics token, and an HTTP host allowlist.
- Keep `requirements.txt` runtime-only; put pytest in `requirements-dev.txt`.
- Do not add a legal license or migrate the queue to a distributed system.
- Do not delete or migrate persistent data or alter provider/workflow interfaces.

---

### Task 1: Seal the Docker build boundary

**Files:** Create `.dockerignore`; modify `Dockerfile` and `tests/test_deployment_config.py`.

**Interfaces:** The image contains runtime dependencies, `src/`, and `plugins/`; it preserves the existing Uvicorn command and standalone vector-memory path.

- [ ] **Step 1: Write the failing test.** Require `.dockerignore` to exclude `.git`, `.worktrees`, `data/`, `tests/`, `docs/`, logs, SQLite files, and JSON runtime files. Require the Dockerfile to avoid `COPY . /app`, copy `requirements.txt` before install, and copy `src` and `plugins`.
- [ ] **Step 2: Verify RED.** Run `python -m pytest tests/test_deployment_config.py -q`; it must fail because `.dockerignore` is absent and Dockerfile still copies the whole repository.
- [ ] **Step 3: Implement minimally.** Add the exclusions and change Dockerfile to `COPY requirements.txt /app/requirements.txt`, install it, then `COPY src /app/src` and `COPY plugins /app/plugins`; retain the existing `ENV`, port, and Uvicorn command.
- [ ] **Step 4: Verify GREEN.** Run the focused tests and `docker build --tag minimal-agent:project-hardening .`; both must exit successfully.
- [ ] **Step 5: Commit.** Run `git add .dockerignore Dockerfile tests/test_deployment_config.py` and `git commit -m "build: restrict container build context"`.

### Task 2: Add fail-closed production configuration

**Files:** Modify `src/agent/config.py`, `docker-compose.yml`, `tests/test_deployment_config.py`, `README.md`, and `docs/AGENT_GUIDE.md`; create `docker-compose.production.yml`.

**Interfaces:** Export `DEPLOYMENT_MODE`; reject unsafe production imports with `ValueError`; preserve development imports and commands.

- [ ] **Step 1: Write failing tests.** Use fresh subprocesses to cover development defaults, disabled production authentication, missing API keys, the default metrics token, a missing HTTP allowlist, and complete production settings. Add tests for required variables in `docker-compose.production.yml`.
- [ ] **Step 2: Verify RED.** Run `python -m pytest tests/test_deployment_config.py -q`; the new tests must fail because deployment mode and production validation do not exist.
- [ ] **Step 3: Implement minimally.** In `config.py`, parse `AGENT_DEPLOYMENT_MODE` with default `development`, reject unknown modes, and in production require enabled auth, one non-`default` `user:key` entry, a non-empty metrics token other than `local-dev-metrics`, and a non-empty HTTP allowlist. Convert base Compose environment to a mapping and add the deployment-mode variable. Create the production override with `AGENT_DEPLOYMENT_MODE=production`, `AGENT_AUTH_REQUIRED=true`, and required interpolation for `AGENT_API_KEYS`, `AGENT_METRICS_API_KEY`, and `AGENT_HTTP_ALLOWED_HOSTS`.
- [ ] **Step 4: Verify GREEN.** Run focused tests, `docker compose config --quiet`, and production Compose rendering once with no required variables (must fail) and once with test-only values (must pass). Document both commands and the single-instance queue boundary.
- [ ] **Step 5: Commit.** Run `git add src/agent/config.py docker-compose.yml docker-compose.production.yml tests/test_deployment_config.py README.md docs/AGENT_GUIDE.md` and `git commit -m "security: fail closed in production mode"`.

### Task 3: Separate runtime dependencies and version metadata

**Files:** Modify `requirements.txt`, `src/agent/server.py`, `tests/test_server.py`, `README.md`, and `CHANGELOG.md`; create `requirements-dev.txt` and `src/agent/version.py`.

**Interfaces:** `src.agent.version.__version__` and `app.version` both equal `0.1.0`; Docker uses runtime dependencies while CI/release use development dependencies.

- [ ] **Step 1: Write failing tests.** Assert pytest is absent from `requirements.txt`, present in `requirements-dev.txt`, and `app.version` equals `src.agent.version.__version__`.
- [ ] **Step 2: Verify RED.** Run `python -m pytest tests/test_server.py -q`; the new dependency/version assertions must fail.
- [ ] **Step 3: Implement minimally.** Remove pytest from runtime requirements; create `requirements-dev.txt` containing `-r requirements.txt` and `pytest==9.1.1`; create `version.py` with `__version__ = "0.1.0"`; pass it to `FastAPI(version=__version__)`.
- [ ] **Step 4: Update metadata.** Set the historical `v0.0.1` changelog date to `2026-08-08`, add a README project description, and document `0.1.0` as the current unreleased version. Do not add a license.
- [ ] **Step 5: Verify and commit.** Run `python -m pytest tests/test_server.py -q`, `python -m pip install -r requirements-dev.txt`, and `python -m pip check`; then commit with `git commit -m "build: separate development dependencies and version metadata"`.

### Task 4: Expand CI and release verification

**Files:** Modify `.github/workflows/ci.yml`, `.github/workflows/release.yml`, and `tests/test_deployment_config.py`.

**Interfaces:** CI and release install development dependencies; CI verifies dependency integrity, Compose rendering, and Docker build.

- [ ] **Step 1: Write failing workflow tests.** Assert both workflows install `requirements-dev.txt` and run `python -m pip check`; assert CI includes `docker compose config --quiet` and a non-pushing `docker build`.
- [ ] **Step 2: Verify RED.** Run `python -m pytest tests/test_deployment_config.py -q`; the new assertions must fail against the current workflows.
- [ ] **Step 3: Implement minimally.** Update both install commands and add `pip check`; add Compose validation and `docker build --tag minimal-agent:ci .` to CI; retain the release service self-check.
- [ ] **Step 4: Verify GREEN.** Run the deployment contract tests and confirm they pass.
- [ ] **Step 5: Commit.** Run `git add .github/workflows/ci.yml .github/workflows/release.yml tests/test_deployment_config.py` and `git commit -m "ci: verify dependencies compose and image builds"`.

### Task 5: Full verification and handoff

**Files:** Modify only documentation if verification exposes an inaccurate command.

- [ ] **Step 1: Run the complete suite.** Run `$env:PYTHONUTF8="1"; python -m pytest -q`; expect all tests to pass with only the existing Windows link skip.
- [ ] **Step 2: Verify dependencies and Compose.** Run `python -m pip check` and both development and complete production `docker compose ... config --quiet` checks; confirm missing production variables fail.
- [ ] **Step 3: Build and smoke-test.** Run `docker build --tag minimal-agent:project-hardening .`, start the image on port 18000, request `/`, and stop the container. Use `Invoke-WebRequest` if a curl container is unavailable.
- [ ] **Step 4: Review scope.** Run `git diff --check`, `git status --short --branch`, and `git log --oneline --decorate -6`; confirm no runtime data is tracked.
- [ ] **Step 5: Report evidence.** Include branch, commits, tests, dependency checks, Compose checks, image build, and the deferred license/distributed-queue decisions. Do not claim multi-instance production readiness.

