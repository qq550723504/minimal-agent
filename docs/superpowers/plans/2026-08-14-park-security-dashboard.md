# Park Security Mock Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free static dashboard that demonstrates the current park-security mock events, evidence, shift context, and in-memory response workflow.

**Architecture:** A single `index.html` owns the semantic markup, styles, mock data, and browser-only state. Rendering is driven by a small state object and explicit functions for KPI, event list, event detail, evidence timeline, shift context, and workflow actions. No MCP, database, credential, or external network call is made.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, Python `http.server`, Node.js syntax check when available, pytest.

## Global Constraints

- Use only deterministic `park-1` mock data aligned with `plugins/park_security/server/mock_fixtures.py` and `mock_repository.py`.
- Do not introduce React, Vue, npm, a bundler, a backend route, database access, MCP calls, or approval-token handling.
- Keep workflow actions in browser memory and enforce `open -> confirmed -> work_order_created -> closed`.
- Escape or assign all displayed values as text; do not execute user-controlled HTML.
- The page must be usable at `http://127.0.0.1:8088/park-security/` when served with `python -m http.server 8088 --directory demos`.

---

### Task 1: Create the static dashboard shell and mock state

**Files:**
- Create: `demos/park-security/index.html`

**Interfaces:**
- `const initialState` contains `events`, `selectedEventId`, `riskFilter`, `statusFilter`, `queryTime`, and `shiftContext`.
- `render()` updates the page from state without network requests.

- [ ] **Step 1: Add the failing smoke expectation**

Create the page with stable IDs for `#event-list`, `#event-detail`, `#evidence-timeline`, `#shift-panel`, `#kpi-total`, `#kpi-critical`, `#kpi-raw`, and `#kpi-rate`; add a visible `MOCK DATA` label and the three event IDs.

- [ ] **Step 2: Run the static smoke check**

Run:

```powershell
if (-not (Test-Path demos/park-security/index.html)) { throw 'dashboard missing' }
Select-String -Path demos/park-security/index.html -Pattern 'event-list','event-detail','event-night-001','event-access-002','event-fire-003'
```

Expected: the file exists and all required IDs/data keys are found.

- [ ] **Step 3: Implement the shell and state**

Add semantic sections for header, KPI cards, filters, event cards, detail metadata, evidence timeline, shift rules, and workflow controls. Embed the three deterministic scenarios with their risk, status, timestamps, impact scopes, recommendations, evidence, responsible teams, and initial audit records.

- [ ] **Step 4: Verify the shell in a local static server**

Run:

```powershell
$job = Start-Job { python -m http.server 8088 --directory demos }
try { Invoke-WebRequest http://127.0.0.1:8088/park-security/ -UseBasicParsing | Select-Object -ExpandProperty StatusCode }
finally { Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force -ErrorAction SilentlyContinue }
```

Expected: HTTP status `200`.

- [ ] **Step 5: Commit**

```powershell
git add demos/park-security/index.html
git commit -m "feat: add park security mock dashboard shell"
```

### Task 2: Render the overview, event details, evidence, and shift context

**Files:**
- Modify: `demos/park-security/index.html`

**Interfaces:**
- `renderKpis()` writes the four KPI values.
- `renderEventList()` applies the current risk/status filters.
- `renderEventDetail()` renders the selected event and action availability.
- `renderTimeline()` renders sorted evidence items.
- `renderShiftContext()` renders the fixed duty and escalation context.

- [ ] **Step 1: Add rendering assertions to the page smoke script**

Expose a small `window.__parkSecurityDemo` object with `getState()` and `render()` so a browser console or a later test can verify the selected event and KPI values without accessing private variables.

- [ ] **Step 2: Implement deterministic rendering**

Render initial KPIs as total events `3`, critical/high events `3`, raw alarms `8`, and effective alarm rate `37.5%`. Default to `event-fire-003`; render its critical risk, three evidence items, `team-fire`, evacuation scope, and the two escalation levels. Sort timeline entries by parsed timestamp.

- [ ] **Step 3: Implement filtering and selection**

Wire risk and status `<select>` controls to state. Re-render cards and detail on change. Clicking an event card sets `selectedEventId`; an empty result shows a clear empty state without throwing.

- [ ] **Step 4: Verify the read-only interactions**

Start the static server, open the page in a browser, and verify all three cards, risk/status filters, event detail, evidence timeline, and shift panel. Confirm the page has no network requests beyond the document itself.

- [ ] **Step 5: Commit**

```powershell
git add demos/park-security/index.html
git commit -m "feat: render park security mock insights"
```

### Task 3: Add the simulated incident response workflow

**Files:**
- Modify: `demos/park-security/index.html`

**Interfaces:**
- `transitionEvent(eventId, nextStatus, operatorId, note)` validates and mutates only in-memory state.
- `window.__parkSecurityDemo.reset()` restores the initial state.

- [ ] **Step 1: Add workflow behavior checks**

Verify the action controls are disabled unless the selected event is in the required state, and define the allowed transitions exactly as `open -> confirmed -> work_order_created -> closed`.

- [ ] **Step 2: Implement confirmation and note input**

Use a native `<dialog>` or an accessible modal requiring a nonblank operator ID and note. Show a second confirmation before applying the transition. Do not request or store an approval token.

- [ ] **Step 3: Implement state, audit, and UI updates**

On confirmation, update status, append an audit record, create a deterministic in-memory work order for the work-order transition, update `work_order_id`, and render a success notice. Reject invalid transitions with a visible message and leave state unchanged.

- [ ] **Step 4: Verify the complete workflow and reset**

Exercise the three transitions on one event, confirm the detail panel and audit timeline update, attempt an out-of-order transition and confirm rejection, then call `window.__parkSecurityDemo.reset()` and confirm all events return to `open` with no work orders.

- [ ] **Step 5: Commit**

```powershell
git add demos/park-security/index.html
git commit -m "feat: demo park security response workflow"
```

### Task 4: Document and verify the demo

**Files:**
- Modify: `plugins/park_security/README.md`
- Test: `tests/infrastructure/plugins/test_park_security.py` (run only; no production test changes required)

**Interfaces:**
- README provides the exact static-server command and dashboard URL.

- [ ] **Step 1: Add the usage documentation**

Add a short “Mock dashboard” section linking the page and documenting that data and workflow state are browser-local demonstrations.

- [ ] **Step 2: Run syntax and repository checks**

Run:

```powershell
node --check demos/park-security/index.html
python -m pytest -q tests/infrastructure/plugins/test_park_security.py
git diff --check
```

If `node --check` cannot inspect HTML directly, extract the inline script to a temporary file for syntax checking and remove the temporary file after verification.

Expected: JavaScript syntax passes, existing park-security tests pass, and `git diff --check` reports no whitespace errors.

- [ ] **Step 3: Commit documentation**

```powershell
git add plugins/park_security/README.md
git commit -m "docs: add park security dashboard usage"
```

