# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Skills、Plugins 和 MCP 运行时：插件清单校验、Skill 目录与安全参考读取、MCP stdio/Streamable HTTP 客户端生命周期，以及 `/api/plugins`、`/api/skills` 目录接口。
- 首个结构化工具调用切片：Planner 输出 `ToolCallPlan`，同步 `/api/handle` 通过 `CapabilityRegistry` 执行本地或 MCP 工具，并统一返回工具状态、稳定错误码和重试语义。
- MCP 工具 allowlist、DNS 地址固定、结果大小限制、未知结果状态和生命周期超时边界。
- Ordered workflow execution for asynchronous plans.
- SQLite persistence for queued workflow definitions, per-step results, retries, and lifecycle events.
- Startup recovery from the first incomplete workflow step with owner-scoped task status reads.
- Optional API Key authentication and per-user task ownership.
- HTTP egress allowlists and private-address protection.
- Prometheus Compose configuration and deployment regression tests.

### Changed
- Vector memory queries are isolated by user and persisted atomically.
- CI now fails when dependency installation fails.
- Compose now forwards capability and MCP runtime limits; plugin runtime remains opt-in and plugin directories are mounted read-only.

### Fixed
- Multi-step queued requests no longer execute as unrelated concurrent tasks.
- Invalid API input is returned as HTTP 400 instead of an unhandled server error.

### Deprecated
-

### Removed
-

### Security
- MCP stdio 精确命令 allowlist、shell 包装器拒绝、HTTP HTTPS/主机 allowlist、SSRF 地址校验、DNS rebinding 防护和 Skill 参考路径 containment。

## [0.0.1] - 2026-08-08

### Added
- Initial minimal Agent architecture and implementation.

### Changed
-

### Fixed
-

### Security
-
