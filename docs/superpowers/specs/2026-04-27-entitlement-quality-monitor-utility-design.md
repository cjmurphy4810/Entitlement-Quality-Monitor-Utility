# Entitlement Quality Monitor Utility — Design

**Date:** 2026-04-27
**Status:** Approved (pending final review)
**Repository:** `cjmurphy4810/Entitlement-Quality-Monitor-Utility`

## 1. Purpose

Build a working simulator of a Data Fabric for entitlement governance that Appian can connect to as a Connected System. The system creates and continuously mutates dummy entitlement, HR, and CMDB records, runs a deterministic, fact-based rules engine over them, emits violations with concrete suggested fixes, and exposes everything via a REST API plus a read-only HTML dashboard.

The simulator is the foundation of a sales demo for moving institutions from hierarchy-based entitlements to controlled, role-based entitlements with continuous Model Risk Management. The rules engine is **strictly deterministic** — no LLMs, no fuzzy matching — so model-risk reviewers can sign off on its behavior.

## 2. Goals and non-goals

**Goals**
- Realistic, version-controlled "data fabric" living in GitHub (auditable history of every change).
- 13 deterministic rules covering entitlement quality, segregation of duties, HR coherence, and CMDB linkage.
- Controllable simulator: scheduled background drift + on-cue scenario injection for live demos.
- REST API surface that lets Appian poll violations, drive a workflow state machine, and apply approved remediations.
- Human-in-the-loop is invariant — every fix requires explicit approve / override / reject in Appian.
- Read-only HTML dashboard for the demo operator to show the data fabric next to the Appian UI.

**Non-goals (explicitly out of scope)**
- Real RBAC on the API (bearer token is sufficient — all data is dummy).
- Multi-tenant deployment.
- Retention/archival of resolved violations beyond JSON storage.
- Production observability (Prometheus, Sentry, etc.).
- A frontend SPA — server-rendered Jinja2 only.
- Appian process-model artifacts — the README documents the connector setup, but the Appian-side build is the user's responsibility.

## 3. Architecture overview

```
GitHub repo (cjmurphy4810/Entitlement-Quality-Monitor-Utility)
│
├── data/                          ← "Data Fabric" — committed JSON files
│   ├── entitlements.json
│   ├── hr_employees.json
│   ├── cmdb_resources.json
│   ├── assignments.json           ← user ↔ entitlement links
│   └── violations.json            ← rules engine output, with workflow state
│
├── src/eqm/
│   ├── models.py                  ← Pydantic schemas (first line of fact-based defense)
│   ├── rules/                     ← one file per rule category
│   │   ├── entitlement_quality.py
│   │   ├── toxic_combinations.py
│   │   ├── hr_coherence.py
│   │   └── cmdb_linkage.py
│   ├── engine.py                  ← runs all rules, emits Violation records, reconciles state
│   ├── simulator.py               ← drift mode
│   ├── scenarios.py               ← named scenarios for demos
│   ├── seed.py                    ← initial dummy data generation (Faker)
│   ├── api.py                     ← FastAPI app
│   ├── dashboard/                 ← Jinja2 HTML templates (read-only)
│   └── persistence.py             ← atomic JSON read/write + git commit
│
├── tests/
│   └── rules/                     ← one unit test file per rule
├── .github/workflows/
│   └── simulate.yml               ← cron drift every 30 min
├── fly.toml                       ← API host
├── Dockerfile
├── pyproject.toml
└── README.md                      ← Appian connector setup guide
```

**Two layers, one shared filesystem:**
- **Files in `data/`** are the source of truth, version-controlled. GitHub Actions writes here on schedule.
- **FastAPI** reads/writes the same files atomically and pushes commits back to GitHub so the audit trail stays intact regardless of who initiated the change.

**Stack**
- Python 3.12, FastAPI, Pydantic v2, Jinja2, Faker, GitPython, pytest.
- Hosted on Fly.io. CI scheduled drift on GitHub Actions.

## 4. Data model

All five entities are persisted as JSON arrays. Pydantic enforces types, enums, and structural invariants — that is the first line of "fact-based, not LLM" validation. The rules engine then layers semantic checks on top.

### 4.1 Enums (shared)

```python
class AccessTier(IntEnum):
    ADMIN = 1            # full admin
    READ_WRITE = 2       # general read/write
    ELEVATED_RO = 3      # elevated, mostly read with some write
    GENERAL_RO = 4       # general read-only

class Role(StrEnum):
    DEVELOPER, OPERATIONS, BUSINESS_USER, BUSINESS_ANALYST, CUSTOMER

class Division(StrEnum):
    CYBER_TECH, TECH_DEV, TECH_OPS, BUSINESS_DEV, BUSINESS_OPS,
    BUSINESS_SALES, LEGAL_COMPLIANCE, FINANCE, HR

class EmployeeStatus(StrEnum):
    ACTIVE, ON_LEAVE, TERMINATED

class ResourceType(StrEnum):
    APPLICATION, SHARE_DRIVE, WEBSITE, DATABASE, API

class Criticality(StrEnum):
    LOW, MEDIUM, HIGH, CRITICAL

class Severity(StrEnum):
    LOW, MEDIUM, HIGH, CRITICAL

class RecommendedAction(StrEnum):
    AUTO_REVOKE_ASSIGNMENT
    UPDATE_ENTITLEMENT_FIELD
    ROUTE_TO_ENTITLEMENT_OWNER
    ROUTE_TO_USER_MANAGER
    ROUTE_TO_COMPLIANCE

class WorkflowState(StrEnum):
    OPEN
    PENDING_APPROVAL
    APPROVED
    REJECTED
    MANUAL_REPAIR
    RESOLVED
```

### 4.2 `Entitlement` — `data/entitlements.json`

```python
class Entitlement(BaseModel):
    id: str                          # ENT-00001
    name: str
    pbl_description: str             # the Plain Business Language field
    access_tier: AccessTier
    acceptable_roles: list[Role]
    division: Division
    linked_resource_ids: list[str]   # → CMDB resource ids
    sod_tags: list[str] = []         # e.g. ["payment_initiate"], drives TOX-01
    created_at: datetime
    updated_at: datetime
```

### 4.3 `HREmployee` — `data/hr_employees.json`

```python
class RoleHistoryEntry(BaseModel):
    role: Role
    division: Division
    started_at: datetime
    ended_at: datetime | None        # None = current

class HREmployee(BaseModel):
    id: str                          # EMP-00001
    full_name: str
    email: str
    current_role: Role
    current_division: Division
    status: EmployeeStatus
    role_history: list[RoleHistoryEntry]   # drives HR-03 (legacy entitlements)
    manager_id: str | None
    hired_at: datetime
    terminated_at: datetime | None
```

### 4.4 `CMDBResource` — `data/cmdb_resources.json`

```python
class CMDBResource(BaseModel):
    id: str                          # RES-00001
    name: str
    type: ResourceType
    criticality: Criticality         # drives CMDB-02
    owner_division: Division
    environment: Literal["dev", "staging", "prod"]
    linked_entitlement_ids: list[str]    # back-reference for CMDB-01
    description: str
```

### 4.5 `Assignment` — `data/assignments.json`

```python
class Assignment(BaseModel):
    id: str                          # ASN-00001
    employee_id: str                 # → HREmployee.id
    entitlement_id: str               # → Entitlement.id
    granted_at: datetime
    granted_by: str                  # employee_id or "system"
    last_certified_at: datetime | None
    active: bool = True
```

### 4.6 `Violation` — `data/violations.json`

```python
class Violation(BaseModel):
    id: str                          # VIO-00001
    rule_id: str                     # e.g. "ENT-Q-01"
    rule_name: str
    severity: Severity
    detected_at: datetime
    target_type: Literal["entitlement", "assignment", "employee", "resource"]
    target_id: str
    explanation: str                 # plain-text "why this is a violation"
    evidence: dict                   # offending fields/values, snapshotted at detection time
    recommended_action: RecommendedAction
    suggested_fix: dict              # concrete patch payload Appian can apply
    workflow_state: WorkflowState = WorkflowState.OPEN
    workflow_history: list[dict] = []     # append-only state transitions
    appian_case_id: str | None = None
```

`workflow_history` entries: `{from_state, to_state, actor, timestamp, note, override_fix?}`. Append-only — every approve / reject / override / manual-repair is captured for audit.

### 4.7 Initial scale (seeded by Faker)

200 entitlements · 500 HR employees · 75 CMDB resources · ~1,200 assignments. Big enough to look real, small enough to keep JSON readable in PR diffs.

## 5. Rules engine

**Design principle:** every rule is a pure Python function. No LLM. No fuzzy matching. Each rule takes a frozen `DataSnapshot`, returns a list of `Violation` objects. Deterministic — same input always produces same output.

### 5.1 The `Rule` contract

```python
class Rule(Protocol):
    id: str                  # "ENT-Q-01"
    name: str
    severity: Severity
    category: str            # entitlement_quality | toxic_combination | hr_coherence | cmdb_linkage
    recommended_action: RecommendedAction

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]: ...
```

`DataSnapshot` is an immutable view of `entitlements`, `hr_employees`, `cmdb_resources`, `assignments`. All rules see the same snapshot per engine run, so results are coherent.

### 5.2 Rule registry

`src/eqm/rules/__init__.py` exposes `ALL_RULES: list[Rule]`. Adding a rule = create a file, register it, write a unit test. No engine changes required.

### 5.3 Engine flow

```
load JSON files  →  build DataSnapshot  →  for rule in ALL_RULES: rule.evaluate(snapshot)
                                       →  reconcile against existing violations.json:
                                            • new violation               → create with state=OPEN
                                            • already exists, still firing → leave as-is (preserve workflow state)
                                            • previously firing, now clean → mark RESOLVED, note: "auto-resolved by drift"
                                       →  atomic write violations.json
                                       →  git commit + push
```

Reconciliation matches by `(rule_id, target_type, target_id)`. A `PENDING_APPROVAL` violation must NOT reset to `OPEN` on the next engine run — the workflow state belongs to Appian until the human acts.

### 5.4 The 13 rules

| ID | Category | Rule | Severity | Recommended action |
|---|---|---|---|---|
| ENT-Q-01 | entitlement_quality | PBL completeness (≥20 chars, no banned phrases: "access stuff", "do things", "admin access") | LOW | UPDATE_ENTITLEMENT_FIELD |
| ENT-Q-02 | entitlement_quality | PBL template match (Tier-1 mentions "administrator" + a system; Tier-4 mentions "read-only") | MEDIUM | ROUTE_TO_ENTITLEMENT_OWNER |
| ENT-Q-03 | entitlement_quality | Tier vs role coherence (Tier-1 cannot include `customer` or `business_user` in `acceptable_roles`) | HIGH | UPDATE_ENTITLEMENT_FIELD |
| ENT-Q-04 | entitlement_quality | Division-resource coherence (HR division entitlements cannot include `developer`; Legal/Compliance cannot be Tier-1 on prod systems) | HIGH | ROUTE_TO_COMPLIANCE |
| TOX-01 | toxic_combination | Maker-checker (same employee holds an entitlement tagged `payment_initiate` AND one tagged `payment_approve`) | CRITICAL | ROUTE_TO_COMPLIANCE |
| TOX-02 | toxic_combination | Dev + Prod-Admin on the same application | CRITICAL | ROUTE_TO_COMPLIANCE |
| TOX-03 | toxic_combination | Tier-1 in 3+ divisions for the same user | HIGH | ROUTE_TO_COMPLIANCE |
| HR-01 | hr_coherence | Role mismatch (employee's current role not in entitlement.acceptable_roles) | MEDIUM | AUTO_REVOKE_ASSIGNMENT |
| HR-02 | hr_coherence | Division mismatch | MEDIUM | AUTO_REVOKE_ASSIGNMENT |
| HR-03 | hr_coherence | Legacy entitlement (role changed ≥30 days ago, still holds prior-role-only entitlement) | HIGH | ROUTE_TO_USER_MANAGER |
| HR-04 | hr_coherence | Terminated user holds active assignment | CRITICAL | AUTO_REVOKE_ASSIGNMENT |
| CMDB-01 | cmdb_linkage | Orphan entitlement (not linked to any CMDB resource) | LOW | ROUTE_TO_ENTITLEMENT_OWNER |
| CMDB-02 | cmdb_linkage | Tier inconsistency (entitlement Tier > 2 on resource with `criticality=high` or `critical`) | HIGH | ROUTE_TO_ENTITLEMENT_OWNER |

**Human-approval invariant:** even rules with `AUTO_REVOKE_ASSIGNMENT` only *suggest* the fix. All changes require human approval in Appian. The recommended action shapes the routing only.

### 5.5 Rule testing

Each rule gets `tests/rules/test_<rule_id>.py` with three tests:
1. Triggering snapshot → engine emits exactly one `Violation` with the expected `suggested_fix`.
2. Clean snapshot → no `Violation` for that rule.
3. Edge case (e.g., HR-03: 29-day-old role change does not fire; 31-day-old does).

This is how we keep "fact-based" honest — every rule's behavior is locked to test cases.

## 6. Simulator

Two modes: drift (background) and scenarios (on-cue).

### 6.1 Drift mode (scheduled, GitHub Actions, every 30 min)

Random, mostly-realistic mutations:

| Mutation | Frequency per tick | Notes |
|---|---|---|
| New employee hired | 0–2 | seeded with role + division, no assignments yet |
| Employee role change | 0–1 | adds a `RoleHistoryEntry`; old assignments NOT auto-removed → seeds HR-03 over time |
| Employee terminated | 0–1 | sets `status=TERMINATED`; active assignments stay → seeds HR-04 |
| Assignment granted | 1–3 | ~70% match acceptable_roles (clean), ~30% mismatch → seeds HR-01/HR-02 |
| Assignment certified | 0–5 | updates `last_certified_at` |
| New entitlement created | 0–1 | ~60% well-formed PBL, ~40% violates ENT-Q-01 or ENT-Q-02 |
| New CMDB resource | 0–1 | sometimes linked, sometimes orphan → seeds CMDB-01 |
| Tier change on entitlement | 0–1 | rare; can introduce ENT-Q-03 / CMDB-02 |

RNG is seeded by tick number for reproducibility. Drift commits with message `chore(simulator): drift tick <N> — +<x> employees, +<y> assignments, ~<z> mutations`.

### 6.2 Scenario mode (manual, `POST /simulate/scenario`)

Pre-built deterministic scenarios for live demos:

| Scenario | Injects | Demo beat |
|---|---|---|
| `terminated_user_with_admin` | 1 HR-04 (CRITICAL) | "Watch — Appian routes this to compliance in <5s" |
| `sod_payment_breach` | 1 TOX-01 (CRITICAL) | "Maker-checker — auto-routed to compliance review" |
| `legacy_entitlements_after_promotion` | 3 HR-03 (HIGH) on one employee | "Promotion 45 days ago, Appian sweeps the stale access" |
| `bad_pbl_batch` | 5 ENT-Q-01 (LOW) + 2 ENT-Q-02 (MEDIUM) | "Quality issues — entitlement owners get a batch review queue" |
| `tier_role_mismatch` | 2 ENT-Q-03 (HIGH) | "Customer role with admin tier — caught instantly" |
| `orphan_entitlements` | 4 CMDB-01 (LOW) | "Cleanup queue for entitlement owners" |
| `kitchen_sink` | 1 of every rule | "Stress-test — Appian's full triage matrix lights up" |

Each scenario commits with message `demo(scenario): <scenario_name>` so git history reads as a demo script.

### 6.3 Determinism + safety invariants

- Every injected violation has a `suggested_fix` that, if applied, restores cleanliness. (No dead-end demos.)
- `POST /simulate/reset` (auth-gated) wipes the data files and re-seeds. One button → fresh slate.
- Drift never injects a violation that breaks a previously-resolved one in the same tick (deduped by target_id).

## 7. API surface

FastAPI app deployed to Fly.io. Bearer-token auth on all writes and `/simulate/*`; reads are open.

### 7.1 Read endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/entitlements` | list, supports `?division=`, `?tier=`, `?limit=`, `?offset=` |
| GET | `/entitlements/{id}` | single record |
| GET | `/hr/employees` | list with filters + pagination |
| GET | `/hr/employees/{id}` | single record + role history |
| GET | `/cmdb/resources` | list |
| GET | `/cmdb/resources/{id}` | single |
| GET | `/assignments` | list, `?employee_id=`, `?entitlement_id=` |
| GET | `/violations` | the main Appian feed; supports `?state=open`, `?severity=critical`, `?since=<ISO>` |
| GET | `/violations/{id}` | single, includes full `workflow_history` |

### 7.2 Write endpoints

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/entitlements/{id}` | apply suggested fix to fields |
| DELETE | `/assignments/{id}` | revoke an assignment |
| PATCH | `/hr/employees/{id}` | manual data correction |
| PATCH | `/cmdb/resources/{id}` | link orphan entitlements |
| POST | `/violations/{id}/transition` | the workflow state machine |
| POST | `/violations/{id}/reopen` | move a REJECTED violation back to OPEN (compliance-driven re-evaluation) |

### 7.3 Workflow state machine

`POST /violations/{id}/transition` body: `{to_state, actor, note, override_fix?}`. Legal transitions:

```
OPEN → PENDING_APPROVAL          (Appian picks it up)
PENDING_APPROVAL → APPROVED      (human approves; fix applied)
PENDING_APPROVAL → REJECTED      (human rejects; reason required in note)
PENDING_APPROVAL → MANUAL_REPAIR (human routes for offline fix)
APPROVED → RESOLVED              (auto, after fix succeeds)
MANUAL_REPAIR → RESOLVED         (human marks complete)
```

`REJECTED` and `RESOLVED` are terminal. Illegal transitions return 409 with the legal options. Every transition appends to `workflow_history`. `override_fix` lets a human modify the suggested patch before applying — that's the approve / override / reject / manual-repair contract.

**Reconciliation rule for REJECTED:** when the engine runs and finds the same `(rule_id, target_type, target_id)` still violating, it does NOT create a new violation if a REJECTED record already exists for that key. Rejection is treated as "compliance-accepted exception" and suppresses re-detection. To re-evaluate a rejected violation, use `POST /violations/{id}/reopen` (auth-gated) which moves it back to OPEN and records the actor/note in `workflow_history`.

### 7.4 Simulator endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/simulate/tick` | one drift tick on demand |
| POST | `/simulate/scenario` | body: `{scenario_name}` |
| POST | `/simulate/reset` | reset to seed (auth required) |
| POST | `/sync/push-now` | force immediate git commit + push |
| POST | `/sync/pull-now` | pull latest data from GitHub and rebuild the in-memory cache |

### 7.5 Auth

Bearer token in `Authorization` header for writes + `/simulate/*` + `/sync/*`. Token in env var `EQM_BEARER_TOKEN`, surfaced in README for Appian connector setup.

## 8. Read-only dashboard

Server-rendered Jinja2 at `GET /`. No SPA. Five tabs:

1. **Overview** — counts by entity, current violation tally by severity, last simulator tick timestamp.
2. **Entitlements** — sortable table; click row → drawer with PBL, linked resources, acceptable roles, current assignments.
3. **HR** — employee table; click row → role history timeline + current assignments.
4. **CMDB** — resources grouped by criticality.
5. **Violations** — live feed, color-coded by severity; click row → full evidence + suggested fix + workflow history.

**Demo control bar** (top of every tab):
- "Run drift tick" button.
- Scenario dropdown + "Inject" button (the seven scenarios).
- "Reset to seed" button (with confirmation).

Gives the demo operator a one-screen view of the data fabric to show alongside the Appian UI.

## 9. Persistence + git integration

**Runtime persistence (Fly volume + periodic git push)**
- API writes to local JSON files on a Fly volume mounted at `/data`.
- A background task pushes to GitHub every 5 min and on every write (debounced).
- `POST /sync/push-now` forces an immediate commit + push for live-demo moments.
- On startup, the API pulls the latest `data/` from GitHub to hydrate the volume.

**Reading drift commits made by GitHub Actions while the API is running.** The API treats its local Fly volume as the source of truth between restarts and does NOT auto-pull during runtime (avoids merge conflicts with in-flight API writes). To pick up scheduled drift commits, the API exposes `POST /sync/pull-now` (auth-gated): pulls from GitHub and rebuilds the in-memory cache. Recommended ops practice during a live demo: pause the GitHub Actions workflow, run the demo entirely off the API + dashboard scenario controls, and re-enable Actions afterward. The README documents this.

**Atomic writes**
- All file writes use a temp-file + `os.replace` pattern.
- A process-wide `asyncio.Lock` serializes writes to each JSON file.
- Read endpoints read from an in-memory cache that's invalidated on write.

**GitHub push auth**
- API uses a `GITHUB_PUSH_TOKEN` (Fly secret) over HTTPS.
- GitHub Actions uses the default `GITHUB_TOKEN` for scheduled drift commits.

## 10. Deployment

**API hosting (Fly.io)**
- Single Dockerized FastAPI app, ~256MB instance.
- Volume mounted at `/data`.
- Public URL: `eqm-utility.fly.dev` (or chosen name).
- Secrets managed via `fly secrets`: `EQM_BEARER_TOKEN`, `GITHUB_PUSH_TOKEN`.

**GitHub Actions (`.github/workflows/simulate.yml`)**
- Cron: `*/30 * * * *`.
- Steps: checkout, setup Python, install deps, `python -m eqm.simulator drift`, commit if changed, push.
- Uses default `GITHUB_TOKEN`.

**Config**
- `EQM_BEARER_TOKEN` — write API auth.
- `GITHUB_PUSH_TOKEN` — for the API to push commits (Fly secret).
- `EQM_DATA_DIR` — defaults to `./data` locally, `/data` on Fly.

## 11. Appian connector setup (README)

Step-by-step for the demo operator:
1. Note the Fly URL and bearer token.
2. Create a Connected System in Appian (HTTP, Bearer auth).
3. Create Integrations for the six endpoints Appian needs:
   - `GET /violations?state=open&severity=critical`
   - `POST /violations/{id}/transition`
   - `PATCH /entitlements/{id}`
   - `DELETE /assignments/{id}`
   - `GET /hr/employees/{id}` (lookup)
   - `GET /entitlements/{id}` (lookup)
4. Build a process model: poll violations every 60s → for each, route by severity → human task screen showing evidence + suggested fix → on approve, call remediation endpoint → on reject, transition to `REJECTED` with note → on manual repair, transition to `MANUAL_REPAIR`.

## 12. Demo storyline (5 minutes)

1. **Set the scene (30s)** — Open the dashboard at `/`. "This is the Data Fabric — 200 entitlements, 500 employees, 75 systems. 14 open violations."
2. **Show the audit trail (30s)** — Open the GitHub repo. Show commit log: `chore(simulator): drift tick 47 …`. "Every change is version-controlled."
3. **Inject a CRITICAL scenario (60s)** — Click `terminated_user_with_admin`. Watch the violation count jump.
4. **Hand off to Appian (90s)** — Switch to Appian. Inbox auto-populates from the new poll. Click the CRITICAL one — human task shows suggested fix with full evidence. "Approve, override, or reject for manual repair."
5. **Approve (30s)** — Click approve. Appian calls `POST /violations/{id}/transition` then `DELETE /assignments/{id}`. Switch back to dashboard — `RESOLVED`. Open workflow history drawer — actor, timestamp, note. Audit-ready.
6. **Show a reject path (45s)** — Pick a MEDIUM PBL violation. Reject in Appian with note. State → `MANUAL_REPAIR`, surfaces in a separate queue.
7. **Close (30s)** — "Hierarchy-based gives you a snapshot. This gives you continuous, fact-based, auditable control. The rules are deterministic, not LLM-generated, so model risk signs off."

Every step is reproducible because the simulator is seeded and scenarios are deterministic.

## 13. Open items / future work

- Rule weights and a composite "entitlement health score" — not in v1.
- Bulk-action endpoints (e.g., approve all LOW violations at once) — not in v1; Appian can call individually.
- Per-user violation history view in the dashboard — could be added later.
- Webhook support for push-based Appian notifications — currently Appian polls; webhook could be added if polling latency becomes a demo issue.
