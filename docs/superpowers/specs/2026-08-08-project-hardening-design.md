# Project Hardening Design

## Goal

Make the current minimal-agent service safer and more reproducible for containerized deployment while preserving the existing local-development defaults and single-process workflow semantics.

## Scope

This change addresses the actionable findings from the project review:

- prevent source-control metadata and runtime data from entering Docker build contexts or image layers;
- make production configuration fail closed without breaking the local `docker compose up` workflow;
- make runtime and development dependencies explicit;
- make CI verify dependency integrity, Compose rendering, and Docker image construction;
- make container versioning, release metadata, and deployment documentation consistent.

The branch does not choose a legal open-source license and does not migrate the SQLite/in-process queue to a distributed system. Those decisions require independent product/legal and deployment-capacity choices.

## Design

### 1. Container boundary

Add a repository-root `.dockerignore` covering `.git`, worktrees, Python caches, test caches, local virtual environments, logs, SQLite files, vector-memory files, and other local-only artifacts. Keep source-controlled runtime configuration such as `prometheus.yml` available only when the image needs it.

Change `Dockerfile` to copy dependency metadata first, install runtime dependencies, and then copy only the runtime source and plugin directory. The image must not copy tests, documentation, Git metadata, local data, or audit logs. The default standalone container path remains `/app/vector_memory.json`; Compose continues to mount `/app/data` for persistent runtime state.

### 2. Production configuration contract

Add an explicit deployment mode setting, `AGENT_DEPLOYMENT_MODE`, with `development` as the default. In `production` mode, configuration validation must require:

- `AGENT_AUTH_REQUIRED=true`;
- at least one non-default `AGENT_API_KEYS` entry;
- a non-empty `AGENT_METRICS_API_KEY` that is not the local development token;
- a non-empty `AGENT_HTTP_ALLOWED_HOSTS` value.

The validation belongs in the existing configuration module so every entry point receives the same fail-closed behavior. The base Compose file remains development-friendly. A new `docker-compose.production.yml` override supplies `AGENT_DEPLOYMENT_MODE=production` and uses required variable interpolation for `AGENT_API_KEYS`, `AGENT_METRICS_API_KEY`, and `AGENT_HTTP_ALLOWED_HOSTS`, so an incomplete production invocation fails during Compose rendering rather than starting an exposed service.

Pin the Prometheus image to an explicit version instead of `latest`. Do not change the tracked development metrics token; document that it is development-only and require a production replacement.

### 3. Dependency and release hygiene

Keep `requirements.txt` limited to runtime packages and create `requirements-dev.txt` that includes the runtime file plus pytest. CI and release validation install the development file; Docker installs only runtime dependencies.

Add `src/agent/version.py` with the service version constant `__version__ = "0.1.0"` and use it for FastAPI metadata. Document that `v0.0.1` is the historical Git tag and that the current unreleased service version is `0.1.0`. Set the unreleased changelog entry to the current date and add a README project description without changing application behavior. The branch will not add a license file because selecting MIT, Apache-2.0, GPL, or another license is a legal decision that must come from the repository owner.

### 4. CI verification

Extend CI with these deterministic checks:

1. install `requirements-dev.txt`;
2. run `python -m pip check`;
3. run the full pytest suite;
4. run `docker compose config --quiet` with development defaults;
5. build the Docker image without pushing it.

Release validation uses the same dependency and test commands and retains the existing service self-check. Tests will cover production configuration rejection, development compatibility, production Compose required variables, the Dockerfile copy boundary, and dependency-file separation. Tests must assert behavior and configuration contracts rather than implementation-only line patterns where practical.

## Error handling and compatibility

- Existing development commands remain valid without API keys.
- Production mode rejects unsafe or incomplete configuration with a clear `ValueError` during import/startup.
- No persistent data is deleted or migrated by this branch.
- Existing at-least-once workflow recovery semantics remain unchanged and will be documented as single-instance behavior.
- The Gemini, OpenAI, mock, plugin, Skill, and MCP interfaces remain unchanged.

## Verification criteria

The work is complete when:

- the new branch has no tracked or untracked runtime data in its Docker build context;
- development Compose renders successfully;
- production Compose fails when required secret/allowlist variables are absent and renders when supplied;
- production configuration tests prove unsafe defaults are rejected;
- `pip check` succeeds;
- the full test suite passes with the expected Windows link test skip and no new warnings;
- the Docker image builds successfully from the reduced context;
- documentation describes the development and production commands accurately.
