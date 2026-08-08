# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Ordered workflow execution for asynchronous plans.
- SQLite persistence for queued workflow definitions, per-step results, retries, and lifecycle events.
- Startup recovery from the first incomplete workflow step with owner-scoped task status reads.
- Optional API Key authentication and per-user task ownership.
- HTTP egress allowlists and private-address protection.
- Prometheus Compose configuration and deployment regression tests.

### Changed
- Vector memory queries are isolated by user and persisted atomically.
- CI now fails when dependency installation fails.

### Fixed
- Multi-step queued requests no longer execute as unrelated concurrent tasks.
- Invalid API input is returned as HTTP 400 instead of an unhandled server error.

### Deprecated
-

### Removed
-

### Security
-

## [0.0.1] - YYYY-MM-DD

### Added
- Initial minimal Agent architecture and implementation.

### Changed
-

### Fixed
-

### Security
-
