# Park Security Mock Repository Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Split `mock_repository.py` by responsibility without changing public imports, MCP behavior, event data, or state transitions.

**Architecture:** Move correlation to `correlation.py`, risk rules to `risk.py`, and deterministic seed/evidence builders to `mock_fixtures.py`. Keep `mock_repository.py` as the in-memory repository and compatibility facade.

**Tech Stack:** Python 3, Pydantic, pytest, existing `plugins.park_security.server` package.

## Global Constraints

- Do not change MCP contracts, response envelopes, event IDs, timestamps, or workflow states.
- Do not add a database, external adapter, or new scenario.
- Preserve imports from `plugins.park_security.server.mock_repository`.
- Run the full test suite and `git diff --check`.

---

### Task 1: Extract correlation domain

**Files:** Create `plugins/park_security/server/correlation.py`; modify `plugins/park_security/server/mock_repository.py`; test `tests/infrastructure/plugins/test_park_security.py`.

**Interfaces:** `correlation.py` provides `CorrelatedAlarmGroup` and `EventCorrelator` with the current constructor and `correlate(alarms)` behavior. `mock_repository.py` imports these names at module scope for compatibility.

- [ ] Write a failing test importing `EventCorrelator` from both modules and asserting identity plus the existing three scenario results.
- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -k "correlator or repository_exposes_three" -q`; it must fail because the new module is absent.
- [ ] Move the dataclass, constants, constructor, `correlate`, spatial grouping, classification, association, and timestamp helpers into `correlation.py`; replace the old definitions with `from .correlation import CorrelatedAlarmGroup, EventCorrelator`.
- [ ] Run the same focused test; it must pass with unchanged scenario IDs and alarm membership.
- [ ] Commit with `git add plugins/park_security/server/correlation.py plugins/park_security/server/mock_repository.py tests/infrastructure/plugins/test_park_security.py && git commit -m "refactor: extract park security correlation"`.

### Task 2: Extract risk rules

**Files:** Create `plugins/park_security/server/risk.py`; modify `plugins/park_security/server/mock_repository.py`; test `tests/infrastructure/plugins/test_park_security.py`.

**Interfaces:** `risk.py` provides `RiskAssessment` and `RiskAssessor.assess(group) -> RiskAssessment`. `mock_repository.py` re-exports both names.

- [ ] Add a failing compatibility test asserting both modules expose the same risk classes and that the three scenarios retain their current risk levels and plans.
- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -k "risk or repository_exposes_three" -q`; it must fail before extraction.
- [ ] Move `RiskAssessment` and `RiskAssessor` plus imports into `risk.py`; import them into `mock_repository.py` without changing values or branching.
- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -q`; it must pass.
- [ ] Commit with `git add plugins/park_security/server/risk.py plugins/park_security/server/mock_repository.py tests/infrastructure/plugins/test_park_security.py && git commit -m "refactor: extract park security risk rules"`.

### Task 3: Extract deterministic Mock fixtures

**Files:** Create `plugins/park_security/server/mock_fixtures.py`; modify `plugins/park_security/server/mock_repository.py`; test `tests/infrastructure/plugins/test_park_security.py`.

**Interfaces:** Implement `build_mock_alarms() -> dict[str, SecurityAlarm]`, `build_event(group: CorrelatedAlarmGroup, assessment: RiskAssessment) -> SecurityEvent`, and `build_timeline(scenario: str, alarms: dict[str, SecurityAlarm]) -> tuple[list[EvidenceItem], str]`.

- [ ] Add failing direct-import tests asserting eight alarms, the three event IDs, and the existing timeline source sets.
- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -k "fixture or repository_exposes_three" -q`; it must fail before the module exists.
- [ ] Move `_evidence`, `_audit`, `_build_alarms`, `_build_event`, and `_build_timeline` into `mock_fixtures.py` as the named functions. Keep repository wrappers that delegate to them:

```python
@staticmethod
def _build_alarms():
    return build_mock_alarms()
```

- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -q`; event summaries, timelines, work orders, and review reports must remain unchanged.
- [ ] Commit with `git add plugins/park_security/server/mock_fixtures.py plugins/park_security/server/mock_repository.py tests/infrastructure/plugins/test_park_security.py && git commit -m "refactor: extract park security mock fixtures"`.

### Task 4: Keep the repository facade focused and verify

**Files:** Modify `plugins/park_security/server/mock_repository.py`; test `tests/infrastructure/plugins/test_park_security.py`.

**Interfaces:** `MockSecurityRepository` retains `list_events`, `get_event`, `save_event`, work-order operations, and `list_shift_context` unchanged. Compatibility exports remain available from `mock_repository.py`.

- [ ] Add a smoke test importing all four moved classes from new modules and the facade, asserting identity equality.
- [ ] Run `PYTHONPATH=. pytest tests/infrastructure/plugins/test_park_security.py -k "import or compatibility" -q` and inspect that the facade has no duplicate correlation, risk, or fixture implementations.
- [ ] Run `PYTHONPATH=. pytest -q`, `git diff --check`, and `git status -sb`; all tests must pass and the worktree must contain only intentional changes.
- [ ] Commit any final facade cleanup with `git add plugins/park_security/server/mock_repository.py tests/infrastructure/plugins/test_park_security.py && git commit -m "refactor: keep park security repository facade focused"`.
