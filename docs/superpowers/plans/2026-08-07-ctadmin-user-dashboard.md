# CTADMIN EQMU Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CTADMIN-branded, authenticated four-page EQMU dashboard with interactive chart filtering, visible user personas, and verified real-data remediation for all 13 rules while preserving the existing `/` dashboard.

**Architecture:** Mount a separate `/ctadmin` FastAPI/Jinja route group with signed server sessions, CSRF protection, server-rendered initial pages, authenticated JSON endpoints, and dependency-free progressive JavaScript/SVG charts. Keep query aggregation, authentication, repair planning, and repair execution in focused modules; remediation mutates an in-memory bundle, evaluates deterministically, verifies that the target condition clears, then persists all affected files atomically.

**Tech Stack:** Python 3.12, FastAPI, Starlette, Pydantic v2, Jinja2, vanilla ES modules, native SVG, pytest, FastAPI TestClient, Ruff.

## Global Constraints

- Preserve the current operational/API-support dashboard at `/` and all existing public API contracts.
- Preserve pre-existing uncommitted user changes, especially `src/eqm/api.py`, `docs/appian/`, `docs/superpowers/reflections/`, and `refresh-data.sh`.
- The new product surface lives under `/ctadmin`; Appian and Wells Fargo branding must not appear there.
- Use the supplied CTADMIN logo from `/Users/zdjimas/Desktop/Screenshot 2026-08-05 at 5.34.05 PM.jpg`.
- Do not introduce Node, React, external chart CDNs, or any runtime network dependency.
- The EQMU bearer token and CTADMIN credential material must never be rendered or sent to the browser.
- Every CTADMIN mutation requires a valid signed session and CSRF token.
- Repair all 13 rule types through validated, previewed actions and report success only when the same rule/target condition clears after evaluation.
- Assignment remediation sets `active=false`; it does not delete assignment records.
- Use test-driven development: observe each focused test fail before implementing its production change.
- Keep modules focused; do not grow `src/eqm/api.py` with CTADMIN page or repair business logic.

---

## Planned File Structure

```text
src/eqm/
├── api.py                              # mount CTADMIN static assets/router only
├── config.py                           # CTADMIN environment settings
├── persistence.py                      # multi-file staged write with rollback
├── projections.py                      # shared public/UI violation projection
└── ctadmin/
    ├── __init__.py                     # template/static paths
    ├── auth.py                         # signed session, CSRF, throttling
    ├── queries.py                      # normalized rows, aggregates, filtering
    ├── repairs.py                      # repair plans for 13 rules
    ├── service.py                      # serialized validate/evaluate/persist flow
    ├── routes.py                       # authenticated HTML/JSON/action routes
    ├── static/
    │   ├── ctadmin.css                 # brand, layout, responsive/accessibility
    │   ├── charts.js                   # accessible native SVG charts
    │   ├── dashboard.js                # filters, fetch, refresh, drawers
    │   └── ctadmin-logo.jpg            # optimized supplied logo
    └── templates/
        ├── base.html                   # authenticated shell/navigation
        ├── login.html                  # branded login
        ├── dashboard.html              # overall health dashboard
        ├── remediation.html            # administrative queue
        ├── finding_detail.html         # evidence/history/repair
        ├── my_findings.html            # visible persona dashboard
        └── _repair_drawer.html          # shared rule-specific form
tests/
├── test_api_projections.py             # public API regression after helper move
├── test_ctadmin_auth.py                # login/session/CSRF/throttle
├── test_ctadmin_queries.py             # metrics/filters/persona
├── test_ctadmin_repairs.py             # all 13 repair plans
├── test_ctadmin_service.py             # mutation/evaluation/rollback/audit
├── test_ctadmin_routes.py              # page/JSON/action integration
├── test_ctadmin_assets.py              # asset/markup/accessibility contracts
└── test_persistence.py                 # multi-file transaction behavior
```

---

### Task 1: CTADMIN Configuration and Signed Authentication

**Files:**
- Modify: `src/eqm/config.py`
- Create: `src/eqm/ctadmin/__init__.py`
- Create: `src/eqm/ctadmin/auth.py`
- Create: `tests/test_ctadmin_auth.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: existing `Settings` and FastAPI `Request`/`Response` cookie APIs.
- Produces: `SessionPrincipal`, `SessionCodec`, `LoginThrottle`, `get_principal(request, settings)`, `require_principal(request, settings)`, `validate_csrf(request, principal)`, and test fixture credentials.

- [ ] **Step 1: Write failing configuration and session-codec tests**

Add explicit CTADMIN test environment values in `app_client`, then test round-trip signing, expiration, tamper rejection, and absence of defaults:

```python
monkeypatch.setenv("EQM_CTADMIN_USERNAME", "demo-admin")
monkeypatch.setenv("EQM_CTADMIN_PASSWORD", "correct-horse-battery-staple")
monkeypatch.setenv("EQM_CTADMIN_SESSION_SECRET", "test-session-secret-at-least-32-bytes")
monkeypatch.setenv("EQM_CTADMIN_SECURE_COOKIES", "0")

def test_session_codec_rejects_tampered_token():
    codec = SessionCodec("a-session-secret-that-is-long-enough", ttl_seconds=3600)
    token = codec.encode("demo-admin", now=1_700_000_000)
    with pytest.raises(InvalidSession):
        codec.decode(token[:-1] + ("a" if token[-1] != "a" else "b"), now=1_700_000_001)
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `.venv/bin/pytest tests/test_ctadmin_auth.py -q`  
Expected: FAIL because `eqm.ctadmin.auth` and CTADMIN settings do not exist.

- [ ] **Step 3: Add explicit settings and implement HMAC-signed sessions**

Add optional settings so existing API deployments still boot without CTADMIN configured:

```python
ctadmin_username: str | None = None
ctadmin_password: SecretStr | None = None
ctadmin_session_secret: SecretStr | None = None
ctadmin_session_ttl_seconds: int = Field(default=28_800, ge=300, le=86_400)
ctadmin_secure_cookies: bool = True
```

Implement a URL-safe JSON payload with `sub`, `exp`, `csrf`, `persona_id`, and `nonce`, signed by HMAC-SHA256. Decode with `hmac.compare_digest`, validate structure/expiry, and expose `require_ctadmin_settings(settings)` that returns HTTP 503 when credentials are not configured. Do not log submitted passwords or session tokens.

- [ ] **Step 4: Implement CSRF validation and bounded in-memory login throttling**

Use `X-CSRF-Token` for JSON and a `csrf_token` form field for HTML actions. Key login failures by normalized username plus client address, allow five failures in five minutes, and clear the key on success:

```python
class LoginThrottle:
    def __init__(self, limit: int = 5, window_seconds: int = 300) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float) -> None:
        recent = self.failures[key]
        while recent and recent[0] <= now - self.window_seconds:
            recent.popleft()
        if len(recent) >= self.limit:
            raise HTTPException(429, "Too many login attempts")

    def record_failure(self, key: str, now: float) -> None:
        self.failures[key].append(now)

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)
```

- [ ] **Step 5: Run authentication unit tests**

Run: `.venv/bin/pytest tests/test_ctadmin_auth.py -q`  
Expected: PASS for round-trip, expiry, tampering, CSRF success/failure, constant-time credential behavior, and throttling.

- [ ] **Step 6: Run lint and commit**

Run: `.venv/bin/ruff check src/eqm/config.py src/eqm/ctadmin tests/test_ctadmin_auth.py tests/conftest.py`  
Expected: PASS.

```bash
git add src/eqm/config.py src/eqm/ctadmin/__init__.py src/eqm/ctadmin/auth.py tests/conftest.py tests/test_ctadmin_auth.py
git commit -m "feat(ctadmin): add signed dashboard sessions"
```

---

### Task 2: Shared Finding Projections and Dashboard Query Model

**Files:**
- Create: `src/eqm/projections.py`
- Create: `src/eqm/ctadmin/queries.py`
- Modify: `src/eqm/api.py` (move/import projection helper without disturbing current changes)
- Create: `tests/test_api_projections.py`
- Create: `tests/test_ctadmin_queries.py`

**Interfaces:**
- Consumes: `Violation`, `JsonStore`, the five EQMU JSON lists.
- Produces: `project_violation(v, emp_by_id, asn_by_id, include_internal=False) -> dict`, `FindingFilters`, `DashboardQueryResult`, `load_dashboard_query(store, filters, persona_id=None) -> DashboardQueryResult`, and `load_personas(store) -> list[dict]`.

- [ ] **Step 1: Pin the existing public projection contract with failing characterization tests**

Assert exact public keys and the internal evidence/history expansion:

```python
assert set(row) == {
    "violationId", "userId", "userName", "ruleId", "ruleName", "status",
    "severity", "reason", "targetType", "targetId", "recommendedAction", "detectedAt",
}
assert detail["suggestedFix"] == {"access_tier": 2}
```

- [ ] **Step 2: Move `_project_violation` into `projections.py` and retain API behavior**

Replace only the helper definition/calls in `api.py`; preserve the user's uncommitted `/api/overview` work and all route signatures.

- [ ] **Step 3: Run public API regression tests**

Run: `.venv/bin/pytest tests/test_api_projections.py tests/test_api_reads.py tests/test_api_user_findings.py -q`  
Expected: PASS with unchanged response shapes.

- [ ] **Step 4: Write failing dashboard aggregate/filter tests**

Create a compact fixture with all severities, states, target types, and two employees. Assert:

```python
filters = FindingFilters(severities=frozenset({"high"}), rules=frozenset())
result = await load_dashboard_query(store, filters)
assert result.kpis.total_findings == 2
assert result.rows[0]["severity"] == "High"
assert result.series["severity"] == [{"key": "high", "label": "High", "count": 2}]
```

Also assert AND semantics across dimensions, active-only defaults, workflow buckets, entitlement coverage, catalog findings, deterministic sort order, pagination metadata, and empty results.

- [ ] **Step 5: Implement immutable filter/query dataclasses and aggregation**

Use normalized lowercase filter keys and derive every KPI/series/table from one filtered row set. A chart's own series ignores only its own active dimension so users can toggle alternative segments while other filters remain applied.

```python
@dataclass(frozen=True, slots=True)
class FindingFilters:
    states: frozenset[str] = frozenset()
    severities: frozenset[str] = frozenset()
    target_types: frozenset[str] = frozenset()
    rules: frozenset[str] = frozenset()
    search: str = ""
```

- [ ] **Step 6: Implement persona scoping and persona options**

Scope exactly to direct employee findings, the employee's active assignments, and entitlements held by active assignments. Return persona options sorted by full name and containing only `id`, `fullName`, `division`, and `role`.

- [ ] **Step 7: Run query tests, full API read tests, lint, and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_queries.py tests/test_api_projections.py tests/test_api_reads.py tests/test_api_user_findings.py -q`  
Run: `.venv/bin/ruff check src/eqm/projections.py src/eqm/ctadmin/queries.py src/eqm/api.py tests/test_api_projections.py tests/test_ctadmin_queries.py`  
Expected: PASS.

```bash
git add src/eqm/projections.py src/eqm/ctadmin/queries.py src/eqm/api.py tests/test_api_projections.py tests/test_ctadmin_queries.py
git commit -m "feat(ctadmin): add shared dashboard query model"
```

---

### Task 3: Branded Login, Protected Router, and Shared Shell

**Files:**
- Create: `src/eqm/ctadmin/routes.py`
- Create: `src/eqm/ctadmin/templates/base.html`
- Create: `src/eqm/ctadmin/templates/login.html`
- Create: `src/eqm/ctadmin/static/ctadmin.css`
- Modify: `src/eqm/api.py`
- Create: `tests/test_ctadmin_routes.py`

**Interfaces:**
- Consumes: Task 1 session helpers and Task 2 query service.
- Produces: `router = APIRouter(prefix="/ctadmin")`, login/logout endpoints, `ctadmin_context(request, principal, **values)`, and protected placeholder routes for the four pages.

- [ ] **Step 1: Write failing login and protected-route tests**

Test redirect behavior, safe `next` handling, cookie flags, credential failure, session rotation, logout, and JSON-vs-page unauthenticated responses:

```python
r = client.get("/ctadmin/dashboard", follow_redirects=False)
assert r.status_code == 303
assert r.headers["location"].startswith("/ctadmin/login")

r = client.post("/ctadmin/login", data={"username": "demo-admin", "password": "correct-horse-battery-staple"}, follow_redirects=False)
assert r.status_code == 303
assert "HttpOnly" in r.headers["set-cookie"]
```

- [ ] **Step 2: Run route tests and confirm failure**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py -q`  
Expected: FAIL because the router/templates are absent.

- [ ] **Step 3: Implement login/logout and route guards**

Use a form POST for login, reject external/scheme-relative `next` values, rotate session on login, and clear the cookie on logout. Page guards redirect to login; `/ctadmin/api/*` and `/ctadmin/actions/*` return 401 JSON.

- [ ] **Step 4: Build the CTADMIN shell and placeholder pages**

Mount CTADMIN assets at `/ctadmin/static`, include the router once in `api.py`, and create navigation for Dashboard, Remediation, and My Findings. Ensure the existing `/static` mount and `/` routes are untouched.

- [ ] **Step 5: Add base visual tokens and accessible login form**

Define CSS custom properties for navy, cyan, neutrals, semantic states, focus ring, spacing, radius, and typography. Login fields require labels, autocomplete attributes, visible errors, and a single primary submit action.

- [ ] **Step 6: Run focused and root-dashboard regressions**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_dashboard.py -q`  
Expected: PASS; root dashboard assertions remain unchanged.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check src/eqm/api.py src/eqm/ctadmin/routes.py tests/test_ctadmin_routes.py
git add src/eqm/api.py src/eqm/ctadmin/routes.py src/eqm/ctadmin/templates/base.html src/eqm/ctadmin/templates/login.html src/eqm/ctadmin/static/ctadmin.css tests/test_ctadmin_routes.py
git commit -m "feat(ctadmin): add authenticated branded shell"
```

---

### Task 4: Health Dashboard JSON Contract and Page

**Files:**
- Create: `src/eqm/ctadmin/templates/dashboard.html`
- Create: `src/eqm/ctadmin/static/charts.js`
- Create: `src/eqm/ctadmin/static/dashboard.js`
- Modify: `src/eqm/ctadmin/routes.py`
- Modify: `src/eqm/ctadmin/static/ctadmin.css`
- Modify: `tests/test_ctadmin_routes.py`
- Create: `tests/test_ctadmin_assets.py`

**Interfaces:**
- Consumes: `load_dashboard_query()` and authenticated/CSRF context.
- Produces: `GET /ctadmin/dashboard`, `GET /ctadmin/api/dashboard`, `renderBarChart(container, series, options)`, `renderDonutChart(container, series, options)`, and `DashboardController`.

- [ ] **Step 1: Write failing HTML and JSON contract tests**

Assert the page contains five KPI hooks, five chart hooks, filter summary, clear button, results table, external JS assets, and no forbidden brands. Assert JSON contains:

```python
assert set(payload) == {"kpis", "coverage", "series", "rows", "filters", "pagination"}
assert set(payload["series"]) == {"status", "severity", "targetType", "rule"}
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py -q`  
Expected: FAIL on missing dashboard markup/assets/API.

- [ ] **Step 3: Implement authenticated dashboard JSON endpoint**

Parse repeated query parameters `state`, `severity`, `targetType`, and `rule`, plus `search`, `page`, and `pageSize`. Reject unsupported values with 422. Return Task 2's normalized result as JSON.

- [ ] **Step 4: Build dashboard markup and initial server payload**

Render accessible KPI cards, labeled chart containers, live filter summary, clear control, and semantic table. Embed only the non-sensitive initial dashboard JSON using Jinja's safe JSON encoding.

- [ ] **Step 5: Implement accessible dependency-free SVG charts**

Each chart renderer creates buttons or focusable SVG groups with `aria-label="High: 12 findings"`, keyboard Enter/Space handlers, visible selection, `<title>` tooltips, numeric labels, and a data attribute for filter dimension/key. Handle all-zero series without invalid geometry.

- [ ] **Step 6: Implement dashboard filter controller**

Maintain a `Map<string, Set<string>>`, serialize repeated query parameters, abort superseded fetches, toggle on click, refresh all components from one response, update browser history, and show a recoverable inline error without discarding the last successful data.

```javascript
toggleFilter(dimension, key) {
  const selected = this.filters.get(dimension) ?? new Set();
  selected.has(key) ? selected.delete(key) : selected.add(key);
  this.filters.set(dimension, selected);
  return this.refresh();
}
```

- [ ] **Step 7: Add responsive dashboard/table styles**

Use CSS grid for KPIs and charts, horizontal table containment below desktop width, explicit focus states, text labels in addition to color, `prefers-reduced-motion`, and a single-column mobile layout.

- [ ] **Step 8: Run route/asset/query regressions and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py tests/test_ctadmin_queries.py tests/test_dashboard.py -q`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/routes.py src/eqm/ctadmin/templates/dashboard.html src/eqm/ctadmin/static/charts.js src/eqm/ctadmin/static/dashboard.js src/eqm/ctadmin/static/ctadmin.css tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py
git commit -m "feat(ctadmin): add interactive health dashboard"
```

---

### Task 5: Rule-Specific Repair Planner for All 13 Rules

**Files:**
- Create: `src/eqm/ctadmin/repairs.py`
- Create: `tests/test_ctadmin_repairs.py`

**Interfaces:**
- Consumes: `Violation`, `SeedBundle`, submitted `dict[str, object]` choices.
- Produces: `RecordMutation`, `RepairPlan`, `RepairValidationError`, `build_repair_plan(violation, bundle, submission) -> RepairPlan`, and `apply_plan(bundle, plan) -> SeedBundle`.

- [ ] **Step 1: Create compact fixture builders and failing direct-edit tests**

Cover ENT-Q-01, ENT-Q-02, ENT-Q-03, ENT-Q-04's two evidence branches, and CMDB-02. Assert exact collection, record ID, before values, after values, and human-readable summary.

```python
plan = build_repair_plan(v, bundle, {"pbl_description": "Read-only access to Ledger API for finance analysts."})
assert plan.mutations[0].changes == {"pbl_description": "Read-only access to Ledger API for finance analysts."}
```

- [ ] **Step 2: Implement typed mutation/plan objects and direct-edit branches**

```python
@dataclass(frozen=True, slots=True)
class RecordMutation:
    collection: Literal["entitlements", "employees", "resources", "assignments"]
    record_id: str
    changes: dict[str, object]

@dataclass(frozen=True, slots=True)
class RepairPlan:
    violation_key: tuple[str, str, str]
    rule_id: str
    summary: str
    choice: dict[str, object]
    mutations: tuple[RecordMutation, ...]
```

Reject blank/template-placeholder PBL text; reject changes that do not differ from current values.

- [ ] **Step 3: Write failing assignment-revocation tests**

Cover HR-01, HR-02, HR-03 manager acknowledgement, and HR-04. Assert only the targeted assignment changes and HR-03 fails without `manager_confirmed=true`.

- [ ] **Step 4: Implement assignment-revocation branches**

Set `active` to `False`; never remove the record. Reject inactive/missing assignments as stale.

- [ ] **Step 5: Write failing ambiguous-compliance tests**

Cover TOX-01 left/right selection, TOX-02 developer/operations selection, and TOX-03 assignment selection. Assert selections are limited to evidence-derived records and the proposed TOX-03 remainder spans at most two Tier-1 divisions.

- [ ] **Step 6: Implement toxic-combination planning**

Resolve evidence entitlement IDs to the affected employee's active assignments. Require explicit submission keys:

```python
{"side": "left"}                         # TOX-01
{"side": "developer"}                    # TOX-02
{"assignment_ids": ["ASN-10", "ASN-11"]} # TOX-03
```

Reject choices outside the current evidence or choices that cannot clear the condition.

- [ ] **Step 7: Write failing orphan-link tests and implement reciprocal linking**

For CMDB-01 require `resource_id`, validate it exists, add it once to `entitlement.linked_resource_ids`, and add the entitlement once to `resource.linked_entitlement_ids`.

- [ ] **Step 8: Add a 13-rule coverage assertion**

```python
assert set(REPAIR_BUILDERS) == {
    "ENT-Q-01", "ENT-Q-02", "ENT-Q-03", "ENT-Q-04",
    "TOX-01", "TOX-02", "TOX-03",
    "HR-01", "HR-02", "HR-03", "HR-04",
    "CMDB-01", "CMDB-02",
}
```

- [ ] **Step 9: Run planner tests, lint, and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_repairs.py -q`  
Run: `.venv/bin/ruff check src/eqm/ctadmin/repairs.py tests/test_ctadmin_repairs.py`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/repairs.py tests/test_ctadmin_repairs.py
git commit -m "feat(ctadmin): plan repairs for all EQMU rules"
```

---

### Task 6: Atomic Multi-File Persistence

**Files:**
- Modify: `src/eqm/persistence.py`
- Modify: `tests/test_persistence.py`

**Interfaces:**
- Consumes: existing `JsonStore.read()`/`write()` behavior.
- Produces: `JsonStore.write_many(documents: dict[str, list[dict] | dict]) -> None` with staging, rollback, and cache update only after success.

- [ ] **Step 1: Write failing transaction success and rollback tests**

Use two seeded files, assert both update on success, then monkeypatch `os.replace` to fail on the second destination and assert both original files and cached reads remain unchanged.

- [ ] **Step 2: Run focused persistence tests and confirm failure**

Run: `.venv/bin/pytest tests/test_persistence.py -q`  
Expected: FAIL because `write_many` is absent.

- [ ] **Step 3: Implement staged multi-file writes**

Under one instance transaction lock: JSON-serialize and fsync all temp files, make same-directory recoverable backups for existing destinations, replace destinations, restore from backups on any exception, remove staging artifacts, and update `_cache` only after every replace succeeds.

- [ ] **Step 4: Run persistence tests and lint**

Run: `.venv/bin/pytest tests/test_persistence.py -q`  
Run: `.venv/bin/ruff check src/eqm/persistence.py tests/test_persistence.py`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/persistence.py tests/test_persistence.py
git commit -m "feat(storage): add recoverable multi-file writes"
```

---

### Task 7: Serialized Repair Execution, Verification, and Audit

**Files:**
- Create: `src/eqm/ctadmin/service.py`
- Create: `tests/test_ctadmin_service.py`

**Interfaces:**
- Consumes: Task 5 `RepairPlan`/`apply_plan`, Task 6 `write_many`, `run_engine`, `transition`, and the five EQMU data files.
- Produces: `RepairReceipt`, `StaleFindingError`, `RepairDidNotClearError`, and `execute_repair(store, violation_id, actor, submission) -> RepairReceipt`.

- [ ] **Step 1: Write failing happy-path service test**

Seed a deterministic ENT-Q-01 finding, execute a valid description repair, and assert:

```python
receipt = await execute_repair(store, "VIO-00001", "demo-admin", submission)
assert receipt.cleared is True
assert receipt.rule_id == "ENT-Q-01"
assert (await store.read("entitlements.json"))[0]["pbl_description"] == submission["pbl_description"]
```

Assert the reconciled violation is resolved and history includes CTADMIN actor plus before/after changes.

- [ ] **Step 2: Implement bundle load, workflow preparation, evaluation, and receipt**

Use a module-level `asyncio.Lock` for CTADMIN repair serialization. For `open`, transition to `pending_approval` then `manual_repair`; for `pending_approval`, transition to `manual_repair`; allow `approved` and `manual_repair` to proceed; reject resolved/rejected. Run the engine and identify success by `(rule_id, target_type, target_id)`, not violation ID.

- [ ] **Step 3: Enrich the engine-generated resolution history**

After the candidate successfully clears, attach actor, summary, selected choice, mutation record IDs, and before/after values to the resolution history entry's note/`override_fix`. Do this before persistence.

- [ ] **Step 4: Write failing non-clear and stale tests**

Use a still-invalid PBL, mutated evidence, inactive assignment, missing violation, and already-resolved violation. Assert typed errors and byte-for-byte unchanged data files.

- [ ] **Step 5: Implement failure-before-persist behavior**

Validate the plan and run the engine entirely in memory. Call `write_many` only after model validation and clear-condition verification succeed.

- [ ] **Step 6: Add representative integration cases for every repair family**

Execute and verify one direct entitlement edit, assignment revocation, multi-assignment toxic repair, reciprocal CMDB link, and TOX-03 constrained choice. Planner tests retain exhaustive 13-rule branch coverage.

- [ ] **Step 7: Run service/engine/persistence tests, lint, and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_service.py tests/test_ctadmin_repairs.py tests/test_persistence.py tests/test_engine.py tests/test_workflow.py -q`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/service.py tests/test_ctadmin_service.py
git commit -m "feat(ctadmin): execute and audit verified repairs"
```

---

### Task 8: Remediation Queue, Repair Drawer, and Finding Detail

**Files:**
- Create: `src/eqm/ctadmin/templates/remediation.html`
- Create: `src/eqm/ctadmin/templates/finding_detail.html`
- Create: `src/eqm/ctadmin/templates/_repair_drawer.html`
- Modify: `src/eqm/ctadmin/routes.py`
- Modify: `src/eqm/ctadmin/static/dashboard.js`
- Modify: `src/eqm/ctadmin/static/ctadmin.css`
- Modify: `tests/test_ctadmin_routes.py`
- Modify: `tests/test_ctadmin_assets.py`

**Interfaces:**
- Consumes: Task 2 queries, Task 5 repair metadata, Task 7 `execute_repair`.
- Produces: `GET /ctadmin/remediation`, `GET /ctadmin/findings/{id}`, `GET /ctadmin/api/findings/{id}/repair-preview`, and `POST /ctadmin/actions/findings/{id}/repair`.

- [ ] **Step 1: Write failing queue/detail/action route tests**

Assert workflow KPI mapping, table columns, pagination, full evidence/history detail, 404 behavior, CSRF rejection, successful repair JSON, and typed 409 responses for stale/non-clearing repairs.

- [ ] **Step 2: Implement remediation query/page**

Map `open` to Not Started; `pending_approval`, `approved`, `manual_repair` to In Progress; `resolved`, `rejected` to Complete. Include state/severity/rule/target/search filters and links preserving origin context.

- [ ] **Step 3: Implement finding-detail page**

Load full internal projection and related target/employee context. Render structured evidence safely, suggested fix, legal workflow state, history, and a repair trigger only for active repairable findings.

- [ ] **Step 4: Implement rule-specific preview JSON and drawer fields**

Return a schema describing one of: PBL textarea, acknowledgement checkbox, CMDB resource select, binary side choice, TOX-03 assignment multiselect, or read-only direct change. Render it in the shared drawer with evidence and exact proposed values.

- [ ] **Step 5: Implement authenticated CSRF-protected repair action**

Pass `principal.username` as actor. Translate `RepairValidationError` to 422, stale/state errors to 409, and unexpected errors to a generic 500 response while logging server detail without secrets.

- [ ] **Step 6: Implement drawer interaction and post-repair refresh**

Trap focus while open, close on Escape/Cancel, disable Confirm while submitting, preserve user input after validation failure, announce outcomes with `aria-live`, and refresh the current query/detail receipt after success.

- [ ] **Step 7: Run routes/assets/service regressions and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py tests/test_ctadmin_service.py -q`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/routes.py src/eqm/ctadmin/templates/remediation.html src/eqm/ctadmin/templates/finding_detail.html src/eqm/ctadmin/templates/_repair_drawer.html src/eqm/ctadmin/static/dashboard.js src/eqm/ctadmin/static/ctadmin.css tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py
git commit -m "feat(ctadmin): add remediation and finding detail"
```

---

### Task 9: My Findings Persona Dashboard

**Files:**
- Create: `src/eqm/ctadmin/templates/my_findings.html`
- Modify: `src/eqm/ctadmin/routes.py`
- Modify: `src/eqm/ctadmin/static/dashboard.js`
- Modify: `src/eqm/ctadmin/static/ctadmin.css`
- Modify: `tests/test_ctadmin_routes.py`
- Modify: `tests/test_ctadmin_assets.py`

**Interfaces:**
- Consumes: Task 2 persona list/scope, Task 4 charts/controller, Task 8 repair drawer/action.
- Produces: `GET /ctadmin/my-findings`, `POST /ctadmin/actions/persona`, and `GET /ctadmin/api/my-findings`.

- [ ] **Step 1: Write failing persona behavior tests**

Assert no-persona prompt, visible employee options, invalid-persona rejection, session persistence after POST, exact user-scoped rows, resolved counts with `include_all`, and persona persistence across navigation/refresh.

- [ ] **Step 2: Implement CSRF-protected persona selection**

Validate employee ID against current HR data, reissue the signed session with `persona_id`, and redirect to a safe relative CTADMIN destination. Clear selection when an empty value is intentionally submitted.

- [ ] **Step 3: Implement My Findings page and JSON**

Render the visible searchable persona selector, employee identity summary, Open/Pending Approval/Resolved cards, severity/rule charts, filters, results table, detail links, and shared Repair triggers.

- [ ] **Step 4: Reuse filter and repair controller behavior**

Configure `DashboardController` with `/ctadmin/api/my-findings`; do not fork a second filtering implementation. On repair success, refresh the persona query and update KPI/chart/table state.

- [ ] **Step 5: Run persona/query/asset tests and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_ctadmin_queries.py tests/test_ctadmin_assets.py -q`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/routes.py src/eqm/ctadmin/templates/my_findings.html src/eqm/ctadmin/static/dashboard.js src/eqm/ctadmin/static/ctadmin.css tests/test_ctadmin_routes.py tests/test_ctadmin_assets.py
git commit -m "feat(ctadmin): add persona-scoped My Findings"
```

---

### Task 10: CTADMIN Logo, Responsive Polish, and Accessibility Contracts

**Files:**
- Create: `src/eqm/ctadmin/static/ctadmin-logo.jpg`
- Modify: `src/eqm/ctadmin/templates/base.html`
- Modify: `src/eqm/ctadmin/templates/login.html`
- Modify: `src/eqm/ctadmin/static/ctadmin.css`
- Modify: `tests/test_ctadmin_assets.py`

**Interfaces:**
- Consumes: supplied JPG source and all completed page templates.
- Produces: optimized local logo asset and final responsive/accessibility styling.

- [ ] **Step 1: Add failing logo and accessibility contract tests**

Assert the logo returns `image/jpeg`, authenticated/login pages include descriptive alt text, every chart has an accessible heading, tables have captions or labeled regions, repair dialog has dialog semantics, and no Appian/Wells Fargo text appears.

- [ ] **Step 2: Create the optimized logo asset from the supplied image**

Use macOS `sips` to preserve the supplied artwork while constraining it to 512px and JPEG quality 82; do not generate a replacement logo:

```bash
sips -Z 512 -s format jpeg -s formatOptions 82 "/Users/zdjimas/Desktop/Screenshot 2026-08-05 at 5.34.05 PM.jpg" --out src/eqm/ctadmin/static/ctadmin-logo.jpg
```

If the exact source filename contains a narrow no-break space, resolve it with `find /Users/zdjimas/Desktop -name 'Screenshot 2026-08-05 at 5.34.05*'` and pass the resolved explicit path.

- [ ] **Step 3: Apply final header/login logo placement and responsive rules**

Keep the logo's black field integrated into the navy header/login card, provide `alt="CTADMIN Technology Administration"`, prevent distortion with `object-fit: contain`, and verify desktop/tablet/mobile/200%-zoom layouts.

- [ ] **Step 4: Add reduced-motion, forced-colors, focus, and print-safe behavior**

Ensure chart selections, buttons, form fields, navigation, and drawer close controls have visible focus. Disable nonessential transitions for reduced motion and keep text/controls discernible in forced-color mode.

- [ ] **Step 5: Run asset tests and commit**

Run: `.venv/bin/pytest tests/test_ctadmin_assets.py tests/test_ctadmin_routes.py -q`  
Expected: PASS.

```bash
git add src/eqm/ctadmin/static/ctadmin-logo.jpg src/eqm/ctadmin/templates/base.html src/eqm/ctadmin/templates/login.html src/eqm/ctadmin/static/ctadmin.css tests/test_ctadmin_assets.py
git commit -m "style(ctadmin): apply CTADMIN brand and accessibility polish"
```

---

### Task 11: Documentation, Full Regression, and Browser Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_e2e.py`
- Create: `docs/ctadmin-dashboard.md`

**Interfaces:**
- Consumes: complete CTADMIN surface.
- Produces: environment/deployment instructions, demo runbook, automated evidence, and browser screenshots/notes.

- [ ] **Step 1: Add the end-to-end happy-path regression test**

Seed deterministic data, log in, select a persona, open a finding, obtain its CSRF-protected repair preview, submit a repair, assert the source record changed and the target condition resolved, then assert updated dashboard and My Findings JSON totals.

- [ ] **Step 2: Run the E2E test and correct any demonstrated integration failure**

Run: `.venv/bin/pytest tests/test_e2e.py tests/test_ctadmin_routes.py -q`  
Expected: PASS. If it fails, make the smallest production or fixture correction that addresses the observed failure, then re-run it.

- [ ] **Step 3: Document configuration and demo workflow**

Document exact environment variables, local login setup, `/ctadmin/login`, persona selection, chart filtering, repair confirmation, data persistence, reset guidance, secure-cookie requirement on Fly.io, and the recommendation to disable scheduled drift during a live demo.

- [ ] **Step 4: Run the complete automated verification suite**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
git diff --check
```

Expected: all tests pass, Ruff passes, and no whitespace errors.

- [ ] **Step 5: Start the local application with explicit demo credentials**

```bash
EQM_DATA_DIR=./data \
EQM_BEARER_TOKEN=demo-token \
EQM_CTADMIN_USERNAME=demo-admin \
EQM_CTADMIN_PASSWORD='local-demo-password' \
EQM_CTADMIN_SESSION_SECRET='local-session-secret-change-before-deploy' \
EQM_CTADMIN_SECURE_COOKIES=0 \
.venv/bin/uvicorn eqm.api:app --port 8080
```

Expected: server listens on `http://127.0.0.1:8080` and existing `/` plus `/ctadmin/login` both return 200.

- [ ] **Step 6: Use the in-app browser workflow for functional and visual QA**

Required skill at execution: `browser:control-in-app-browser`. Verify login, all navigation, chart click/keyboard filters, combined filters, clear filters, persona selection/persistence, finding detail, repair preview/cancel/confirm, post-repair refresh, logout, and expired/invalid session behavior. Capture desktop, tablet, and mobile screenshots and compare hierarchy/density with the reference screenshots while confirming CTADMIN-only branding.

- [ ] **Step 7: Verify a real repair against a disposable copied data directory**

Run the browser/server with a temporary copied `EQM_DATA_DIR`, complete a repair, and confirm both the UI outcome and JSON before/after. Do not mutate the repository's tracked demo data during verification.

- [ ] **Step 8: Review the complete diff for scope and secret safety**

Run:

```bash
git status --short
git diff --stat HEAD~10..HEAD
rg -n "demo-token|local-demo-password|session-secret" src tests docs README.md
```

Expected: only documentation/test examples contain placeholder demo values; no real credentials, Appian branding, or Wells Fargo branding appear in the CTADMIN assets/templates.

- [ ] **Step 9: Commit documentation and final integration fixes**

```bash
git add README.md docs/ctadmin-dashboard.md tests/test_e2e.py tests/test_ctadmin_routes.py
git commit -m "docs(ctadmin): add dashboard demo runbook"
```

---

### Task 12: Final Review and Completion Evidence

**Files:**
- Review only: all files changed by Tasks 1-11.

**Interfaces:**
- Consumes: complete implementation and verification output.
- Produces: reviewed implementation ready for user handoff.

- [ ] **Step 1: Invoke the required review skills**

Use `superpowers:requesting-code-review` for an implementation/spec review, address valid findings with focused tests, then use `superpowers:verification-before-completion` before making success claims.

- [ ] **Step 2: Re-run final verification after review fixes**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
git diff --check
git status --short
```

Expected: tests and lint pass; status contains only the user's known pre-existing changes plus intentional committed work.

- [ ] **Step 3: Confirm acceptance criteria explicitly**

Record evidence that the branded login, four pages, chart filtering, persona switching, all-13 repair registry, real-data mutation, target-condition clearing, session/CSRF security, existing root dashboard regression, and responsive browser checks each passed.

- [ ] **Step 4: Prepare the user handoff**

Report the feature routes, configured environment variables, test counts/results, browser verification summary, intentionally deferred production-hardening items, and the exact pre-existing worktree changes that were preserved.
