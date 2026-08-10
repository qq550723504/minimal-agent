# Full Layered Architecture Design

## Goal

Reorganize the `src/agent` package into explicit API, application, domain, infrastructure, and security layers. Preserve all runtime behavior, HTTP endpoints, environment variables, plugin manifests, and test coverage while replacing every project import with its new canonical path. No compatibility re-export modules will remain at the previous root-level paths.

## Target Structure

```text
src/agent/
  api/
    app.py
    routes/
    schemas.py
  application/
    requests.py
    planning/
    execution/
  domain/
    capabilities/
    planning/
  infrastructure/
    llm/
    memory/
    workflows/
    mcp/
    plugins/
    skills/
  security/
  tools/
  config.py
  observability.py
  version.py
```

## Boundaries and Dependencies

`api` owns FastAPI app construction, routes, request/response schemas, and lifespan wiring. It calls `application` and must not contain planning, execution, persistence, or provider logic.

`application` owns request handling, plan creation, execution orchestration, and queue use cases. It depends on `domain` models and invokes infrastructure implementations through their public modules.

`domain` contains provider- and framework-independent plan and capability models, validation rules, and errors. It does not import API or infrastructure modules.

`infrastructure` contains model adapters and factories, embeddings and vector memory, SQLite workflow persistence and queues, MCP transport/client integration, and plugin and skill loading.

`security` contains API authentication, input sanitization, audit logging, HTTP URL safeguards, and MCP transport security. It remains framework-neutral except for explicit API dependency adapters.

`tools` remains the home for built-in tool definitions and registration. It uses domain capability contracts and security helpers.

Dependencies flow inward: `api -> application -> domain`. Infrastructure supplies implementations used by application and tools without depending on API. `config`, `observability`, and `version` remain narrow cross-cutting modules at package root.

## Migration

Split the current server module into app setup, route modules, and schemas. Move the current main, planner, and executor responsibilities into application request, planning, and execution modules. Move LLM, embedding, memory, queue/store, MCP, plugins, and skills modules into their matching infrastructure subpackages. Move plan models and capabilities into domain.

Update all production modules, tests, documentation examples, and startup commands to canonical module paths. Delete all superseded root-level modules rather than retaining compatibility shims. Preserve all HTTP paths, application lifespan behavior, authentication, queue recovery, structured tool calling, MCP safeguards, and plugin manifest formats unchanged.

## Verification

Run the complete pytest suite. Verify that the FastAPI application imports successfully, its OpenAPI schema remains available, and the documented uvicorn import target resolves. Confirm no project import references a removed root-level module.

## Non-goals

This work does not redesign runtime behavior, external APIs, configuration names, persistence schema, plugin contracts, or test semantics. It is an organizational refactor only.
