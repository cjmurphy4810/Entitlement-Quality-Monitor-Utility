# EQMU "My Findings" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-user remediation interface to the EQMU Appian site, with embedded PBL Evaluator iframe for fixing low-quality entitlement descriptions and write-back to the Fly data fabric to clear violations.

**Architecture:** Three repos work together. EQM Fly backend gets one new read endpoint that joins findings to a user. PBL Evaluator frontend reads URL parameters on its Evaluate page to pre-populate the form. Appian gets five new integrations, two constants, one Site page, and one SAIL interface (`EQMU_MyFindings`) with KPI cards, a filterable grid, and a drill-down panel that branches on finding type — PBL findings render an iframe + write-back form, non-PBL findings render details + a generic "Mark as Resolved" button.

**Tech Stack:** Python 3.12 / FastAPI / pytest (EQM backend); React 19 / TypeScript / Vite (PBL Evaluator frontend); Appian SAIL + Integration objects (Appian).

**Reference spec:** [`2026-05-02-eqmu-my-findings-design.md`](../specs/2026-05-02-eqmu-my-findings-design.md)

---

## Phase 0: Iframe feasibility spike

De-risk the highest-risk unknown first. If Appian's CSP blocks `pbl-evaluator.fly.dev` from loading inside an iframe, the entire feature pivots from "embed" to "open in new tab" — better to know now than after building the SAIL.

### Task 0.1: Drop a test webContentField into an existing interface

**Files:**
- Modify in Appian: `EQMU_FindingDetail` (a copy of the source — DO NOT save the experimental version)

- [ ] **Step 1: Open `EQMU_FindingDetail` in Appian Designer**

- [ ] **Step 2: Save its current SAIL to a scratch file**

```bash
# Manual — copy the entire interface body into a scratch.txt locally
# so you can restore it cleanly. Don't rely on Appian's undo across save boundaries.
```

- [ ] **Step 3: At the top of the section's `contents:` list, prepend a webContentField**

```
a!webContentField(
  label: "PBL Evaluator embed test",
  url: "https://pbl-evaluator.fly.dev/",
  height: "MEDIUM"
),
```

- [ ] **Step 4: Save the interface and load `/page/finding?violationId=VIO-00001` on the live site**

- [ ] **Step 5: Verify the PBL Evaluator nav bar renders inside the embedded frame**

Open browser DevTools (F12), check for any `Refused to display 'https://pbl-evaluator.fly.dev/' in a frame because it set 'X-Frame-Options'` or `Refused to frame ... because an ancestor violates the following Content Security Policy directive` errors in the Console.

- [ ] **Step 6: Restore the original SAIL from your scratch file**

If the iframe rendered: proceed to Phase 1.

If the iframe was blocked: STOP. Open a session to either (a) configure Appian's site CSP to allow `frame-src https://pbl-evaluator.fly.dev` (admin work), or (b) pivot the design to "Open PBL Evaluator in new tab" via `a!safeLink`. Update the spec accordingly before resuming this plan.

---

## Phase 1: EQM `/api/user-findings` endpoint

Add the per-user findings endpoint to the Fly backend. Test-driven against existing pytest patterns.

### File structure

- Modify: `src/eqm/api.py` — add the endpoint
- Create: `tests/test_api_user_findings.py` — tests for the new endpoint

### Task 1.1: Test scaffolding — direct user-targeted findings

**Files:**
- Test: `tests/test_api_user_findings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_user_findings.py` with this content:

```python
import json


def _seed_basic(tmp_path):
    """Seed entitlements, employees, assignments, and a few violations."""
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "DB Admin", "pbl_description": "Admin access for DBAs.",
         "access_tier": 1, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00",
         "updated_at": "2025-01-01T00:00:00+00:00"},
        {"id": "ENT-2", "name": "Reporting", "pbl_description": "Read-only reports.",
         "access_tier": 4, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00",
         "updated_at": "2025-01-01T00:00:00+00:00"},
    ]))
    (tmp_path / "hr_employees.json").write_text(json.dumps([
        {"id": "EMP-1", "full_name": "Alex Doe", "email": "alex@example.com",
         "current_role": "operations", "current_division": "tech_ops",
         "status": "active", "role_history": [],
         "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
         "terminated_at": None},
        {"id": "EMP-2", "full_name": "Sam Roe", "email": "sam@example.com",
         "current_role": "operations", "current_division": "tech_ops",
         "status": "active", "role_history": [],
         "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
         "terminated_at": None},
    ]))
    (tmp_path / "cmdb_resources.json").write_text("[]")
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True},
        {"id": "ASN-2", "employee_id": "EMP-2", "entitlement_id": "ENT-2",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True},
    ]))
    (tmp_path / "violations.json").write_text("[]")


def test_user_findings_returns_data_envelope(app_client, tmp_path):
    """Endpoint returns {"data": [...]} matching /api/flagged-records shape."""
    client, _ = app_client
    _seed_basic(tmp_path)

    r = client.get("/api/user-findings?userId=EMP-1")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert isinstance(body["data"], list)


def test_user_findings_direct_user_target(app_client, tmp_path):
    """A violation with target_type=user matching the userId is returned."""
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "HR-01", "rule_name": "Terminated user holds assignment",
         "severity": "high", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "user", "target_id": "EMP-1",
         "explanation": "...", "evidence": {}, "recommended_action": "revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert len(body["data"]) == 1
    assert body["data"][0]["violationId"] == "VIO-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_user_findings.py -v`
Expected: FAIL with `404 Not Found` (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the endpoint — minimum to pass first test**

Open `src/eqm/api.py` and add this endpoint right after `/api/overview` (around line 308 — after the `get_overview` function ends and before the `ENTITLEMENT_PATCHABLE = {...}` constant):

```python
@app.get("/api/user-findings")
async def get_user_findings(
    userId: str,
    include_all: bool = False,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> dict:
    """Findings touching a specific user.

    Joins three categories of findings:
    1. target_type=user AND target_id=userId
    2. target_type=assignment AND assignment.employee_id=userId
    3. target_type=entitlement AND entitlement_id IN
       (active assignments where employee_id=userId)

    Returns ``{"data": [...]}`` matching the ``/api/flagged-records`` shape.
    Excludes resolved/rejected by default; pass ``include_all=true`` for parity.
    """
    raw_vios = await _read_list(store, "violations.json")
    raw_emps = await _read_list(store, "hr_employees.json")
    raw_asns = await _read_list(store, "assignments.json")
    emp_by_id = {e["id"]: e for e in raw_emps}
    asn_by_id = {a["id"]: a for a in raw_asns}

    user_assignment_ids: set[str] = set()
    user_entitlement_ids: set[str] = set()
    for a in raw_asns:
        if a["employee_id"] == userId and a.get("active", True):
            user_assignment_ids.add(a["id"])
            user_entitlement_ids.add(a["entitlement_id"])

    items: list[Violation] = []
    seen: set[str] = set()
    for v in raw_vios:
        if not include_all and v.get("workflow_state") in ("resolved", "rejected"):
            continue
        ttype = v.get("target_type")
        tid = v.get("target_id")
        match = (
            (ttype == "user" and tid == userId) or
            (ttype == "assignment" and tid in user_assignment_ids) or
            (ttype == "entitlement" and tid in user_entitlement_ids)
        )
        if match and v["id"] not in seen:
            items.append(Violation(**v))
            seen.add(v["id"])

    return {"data": [_project_violation(v, emp_by_id, asn_by_id) for v in items]}
```

- [ ] **Step 4: Run tests, both should pass**

Run: `pytest tests/test_api_user_findings.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd "/Users/zdjimas/VS Code Projects/Entitlement-Quality-Monitor-Utility"
git add src/eqm/api.py tests/test_api_user_findings.py
git commit -m "feat(api): add /api/user-findings endpoint with direct-user-target match"
```

### Task 1.2: Test the assignment-target join

**Files:**
- Test: `tests/test_api_user_findings.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_api_user_findings.py`:

```python
def test_user_findings_assignment_target_via_user_assignment(app_client, tmp_path):
    """A violation with target_type=assignment for one of the user's assignments is returned."""
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-2", "rule_id": "TOX-01", "rule_name": "Excessive privilege",
         "severity": "medium", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "assignment", "target_id": "ASN-1",
         "explanation": "...", "evidence": {}, "recommended_action": "revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert len(body["data"]) == 1
    assert body["data"][0]["violationId"] == "VIO-2"


def test_user_findings_assignment_target_excludes_other_users(app_client, tmp_path):
    """An assignment-target finding for someone else's assignment is NOT returned."""
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-3", "rule_id": "TOX-01", "rule_name": "Excessive privilege",
         "severity": "medium", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "assignment", "target_id": "ASN-2",
         "explanation": "...", "evidence": {}, "recommended_action": "revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert body["data"] == []
```

- [ ] **Step 2: Run, both should pass without code changes**

Run: `pytest tests/test_api_user_findings.py -v`
Expected: 4 passed (the assignment-target logic is already in the implementation from Task 1.1; these tests just lock the behavior in).

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_user_findings.py
git commit -m "test(api): cover assignment-target user-findings join"
```

### Task 1.3: Test the entitlement-target join (the PBL flow path)

**Files:**
- Test: `tests/test_api_user_findings.py` (extend)

- [ ] **Step 1: Add the failing test**

```python
def test_user_findings_entitlement_target_via_user_assignment(app_client, tmp_path):
    """A violation with target_type=entitlement for an entitlement the user holds is returned.

    This is the path that surfaces PBL completeness / template findings to the assigned user.
    """
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-4", "rule_id": "ENT-Q-01", "rule_name": "PBL completeness",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "PBL too short", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert len(body["data"]) == 1
    assert body["data"][0]["violationId"] == "VIO-4"
    assert body["data"][0]["ruleName"] == "PBL completeness"


def test_user_findings_entitlement_target_excludes_unassigned(app_client, tmp_path):
    """An entitlement finding the user is NOT assigned to should not appear."""
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-5", "rule_id": "ENT-Q-01", "rule_name": "PBL completeness",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-2",
         "explanation": "...", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert body["data"] == []


def test_user_findings_inactive_assignment_excludes_entitlement(app_client, tmp_path):
    """If the user's assignment is inactive, entitlement-target findings should not appear."""
    client, _ = app_client
    _seed_basic(tmp_path)
    asns = json.loads((tmp_path / "assignments.json").read_text())
    asns[0]["active"] = False
    (tmp_path / "assignments.json").write_text(json.dumps(asns))
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-6", "rule_id": "ENT-Q-01", "rule_name": "PBL completeness",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "...", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert body["data"] == []
```

- [ ] **Step 2: Run, all should pass**

Run: `pytest tests/test_api_user_findings.py -v`
Expected: 7 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_user_findings.py
git commit -m "test(api): cover entitlement-target user-findings join with active-assignment filter"
```

### Task 1.4: Test workflow-state filtering and dedup

**Files:**
- Test: `tests/test_api_user_findings.py` (extend)

- [ ] **Step 1: Add tests for state filtering and dedup**

```python
def test_user_findings_excludes_resolved_by_default(app_client, tmp_path):
    """Resolved violations are excluded unless include_all=true."""
    client, _ = app_client
    _seed_basic(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-7", "rule_id": "HR-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "user", "target_id": "EMP-1",
         "explanation": "...", "evidence": {}, "recommended_action": "revoke_assignment",
         "suggested_fix": {}, "workflow_state": "resolved", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body_default = client.get("/api/user-findings?userId=EMP-1").json()
    assert body_default["data"] == []

    body_all = client.get("/api/user-findings?userId=EMP-1&include_all=true").json()
    assert len(body_all["data"]) == 1


def test_user_findings_no_dedup_across_categories(app_client, tmp_path):
    """A violation that matches multiple categories should appear only once."""
    client, _ = app_client
    _seed_basic(tmp_path)
    # A violation can't actually be both user-target and entitlement-target simultaneously
    # in the data model, but the seen-set guards against double-add bugs anyway.
    # This test seeds two distinct violations both touching EMP-1 and asserts both appear.
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-A", "rule_id": "HR-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "user", "target_id": "EMP-1",
         "explanation": "...", "evidence": {}, "recommended_action": "revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None},
        {"id": "VIO-B", "rule_id": "ENT-Q-01", "rule_name": "PBL completeness",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "...", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None},
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    ids = [d["violationId"] for d in body["data"]]
    assert sorted(ids) == ["VIO-A", "VIO-B"]
```

- [ ] **Step 2: Run, all should pass**

Run: `pytest tests/test_api_user_findings.py -v`
Expected: 9 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_user_findings.py
git commit -m "test(api): cover workflow-state filter and multi-finding dedup"
```

### Task 1.5: Deploy to Fly and smoke-test

**Files:** No file changes — deployment.

- [ ] **Step 1: Deploy**

```bash
cd "/Users/zdjimas/VS Code Projects/Entitlement-Quality-Monitor-Utility"
flyctl deploy
```

Expected: deploy completes, machine state "good".

- [ ] **Step 2: Smoke-test the new endpoint**

```bash
curl -s "https://eqm-utility.fly.dev/api/user-findings?userId=EMP-00001" | head -c 500
```

Expected: JSON `{"data": [...]}` with non-empty array (assuming EMP-00001 has at least one finding in the current scenario).

- [ ] **Step 3: Pick a demo employee with varied finding types**

```bash
# Find an employee with both PBL findings and other finding types
for emp in EMP-00001 EMP-00010 EMP-00020 EMP-00050 EMP-00100; do
  count=$(curl -s "https://eqm-utility.fly.dev/api/user-findings?userId=$emp" | python3 -c "import sys, json; d = json.load(sys.stdin); print(len(d['data']))")
  pbl=$(curl -s "https://eqm-utility.fly.dev/api/user-findings?userId=$emp" | python3 -c "import sys, json; d = json.load(sys.stdin); print(sum(1 for x in d['data'] if 'PBL' in x.get('ruleName','')))")
  echo "$emp: $count total, $pbl PBL"
done
```

Pick an employee with **both at least 1 PBL finding AND at least 1 non-PBL finding**. Record the chosen ID — this is what `cons!EQMU_DEMO_USER_ID` becomes.

---

## Phase 2: PBL Evaluator URL parameter pre-population

The Evaluate page needs to read URL query parameters on mount and seed the form's initial state. Manual browser verification — no test infrastructure exists in this frontend.

### File structure

- Modify: `frontend/src/pages/Evaluate.tsx`

### Task 2.1: Read URL params on Evaluate mount

**Files:**
- Modify: `frontend/src/pages/Evaluate.tsx:1-26`

- [ ] **Step 1: Add the import for useSearchParams**

Open `frontend/src/pages/Evaluate.tsx`. Change line 1:

```typescript
import { useState } from "react";
```

to:

```typescript
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
```

- [ ] **Step 2: Replace the INITIAL constant with a function that reads URL params**

Replace lines 12-20:

```typescript
const INITIAL: EvaluateRequest = {
  name: "",
  description: "",
  resource_type: "",
  resource_name: "",
  access_level: "read",
  roles: [],
  divisions: [],
};
```

with:

```typescript
function initialFromParams(params: URLSearchParams): EvaluateRequest {
  return {
    name: params.get("name") ?? "",
    description: params.get("description") ?? "",
    resource_type: params.get("resourceType") ?? "",
    resource_name: params.get("resourceName") ?? "",
    access_level: params.get("accessLevel") ?? "read",
    conditions: params.get("conditions") ?? undefined,
    business_justification: params.get("businessJustification") ?? undefined,
    roles: [],
    divisions: [],
  };
}
```

- [ ] **Step 3: Use the function inside the component**

Replace line 26:

```typescript
const [form, setForm] = useState<EvaluateRequest>(INITIAL);
```

with:

```typescript
const [searchParams] = useSearchParams();
const [form, setForm] = useState<EvaluateRequest>(() => initialFromParams(searchParams));
```

- [ ] **Step 4: Verify the file compiles locally (in CI build container)**

```bash
cd "/Users/zdjimas/VS Code Projects/PBL-Evaluator/frontend"
# If node_modules isn't installed locally, skip this and rely on Docker build
npm install --no-save 2>/dev/null && npx tsc -b --noEmit
```

Expected: no TypeScript errors. If `npm install` fails (no Node), skip — Docker build will catch it.

- [ ] **Step 5: Deploy to Fly**

```bash
cd "/Users/zdjimas/VS Code Projects/PBL-Evaluator"
flyctl deploy
```

Expected: build succeeds, machine state "good".

- [ ] **Step 6: Browser-verify pre-population**

Open in browser:

```
https://pbl-evaluator.fly.dev/evaluate?name=Test%20Entitlement&description=Some%20PBL%20text&resourceType=database&resourceName=PROD&accessLevel=admin
```

Expected: the form fields **Name**, **Description**, **Resource Type**, **Resource Name**, and **Access Level** are pre-filled with the values from the URL. The "Submit" button should be active because all required fields are populated.

- [ ] **Step 7: Commit**

```bash
cd "/Users/zdjimas/VS Code Projects/PBL-Evaluator"
git add frontend/src/pages/Evaluate.tsx
git commit -m "feat(evaluate): pre-populate form from URL search parameters

Enables embedding the evaluator in an iframe with the entitlement under
remediation passed via URL params. Used by EQMU MyFindings dashboard."
```

---

## Phase 3: Appian — constants and integrations

Manual configuration in Appian Designer. No automated tests; verify each integration with the TEST button.

### Task 3.1: Create the two constants

- [ ] **Step 1: Open Appian Designer → EQMU app → Constants → New Constant**

- [ ] **Step 2: Create `EQMU_DEMO_USER_ID`**

| Field | Value |
|---|---|
| Name | `EQMU_DEMO_USER_ID` |
| Type | Text |
| Value | The employee ID picked in Task 1.5 Step 3 (e.g., `EMP-00042`) |
| Description | Demo persona for the My Findings interface. Override mid-demo via `?demoUserId=...` URL param. |

Save.

- [ ] **Step 3: Create `EQMU_PBL_EVALUATOR_URL`**

| Field | Value |
|---|---|
| Name | `EQMU_PBL_EVALUATOR_URL` |
| Type | Text |
| Value | `https://pbl-evaluator.fly.dev/evaluate` |
| Description | Embed URL for the PBL Evaluator iframe in the My Findings drill-down. |

Save.

### Task 3.2: Create `EQMU_getMyFindings` integration

- [ ] **Step 1: Duplicate `EQMU_getAllFindings`**

In Appian Designer, right-click `EQMU_getAllFindings` → Duplicate. Name the copy `EQMU_getMyFindings`. Description: `Findings touching a specific user (direct, assignment-targeted, and entitlement-targeted via active assignments).`

- [ ] **Step 2: Configure the integration**

| Field | Value |
|---|---|
| URL | `https://eqm-utility.fly.dev/api/user-findings?userId=` followed by an expression input that reads `ri!userId` (use the URL builder UI to append the rule input as a value, NOT a path template) |
| Method | GET |
| Query Parameters | `userId` mapped to `ri!userId` |
| Path Parameters | none |
| Body | none |
| Headers | none required (open endpoint) |
| Usage | Queries data |
| Response Body Parsing | Return raw response body |

The simplest approach: leave the URL as just `https://eqm-utility.fly.dev/api/user-findings`, and add a single Query Parameter row with Name `userId` and Value `=ri!userId`.

- [ ] **Step 3: Add the rule input**

In the right sidebar, add a Rule Input:
- Name: `userId`
- Type: Text
- Required: yes

- [ ] **Step 4: Test**

Set the rule input test value to your demo employee ID. Click TEST.
Expected: response body is `{"data": [...]}` with the user's findings.

- [ ] **Step 5: Save**

### Task 3.3: Create `EQMU_getEntitlementById` integration

- [ ] **Step 1: Duplicate `EQMU_getAllFindings` again**

Rename to `EQMU_getEntitlementById`. Description: `Fetch a single entitlement by ID, used to pre-populate the PBL Evaluator iframe.`

- [ ] **Step 2: Configure**

| Field | Value |
|---|---|
| URL | `https://eqm-utility.fly.dev/entitlements/` then append `=ri!entitlementId` as the path tail (use the expression mode of the URL field — concatenate strings) |
| Method | GET |
| Query Parameters | none |
| Body | none |

A reliable way: set the URL field expression to `="https://eqm-utility.fly.dev/entitlements/" & ri!entitlementId`.

- [ ] **Step 3: Add rule input `entitlementId` (Text, Required)**

- [ ] **Step 4: Test**

Set test value to a known entitlement ID (e.g., `ENT-00001`). Click TEST.
Expected: response body contains entitlement fields including `pbl_description`, `access_tier`, `name`.

- [ ] **Step 5: Save**

### Task 3.4: Create `EQMU_updateEntitlementPBL` integration

- [ ] **Step 1: New Integration → Connected System: `EQMU Fly Backend API` (the existing one with bearer token)**

If duplicating an existing modify-data integration is easier, duplicate any one that uses the bearer token (e.g., a transition integration if you already have one — otherwise start fresh).

| Field | Value |
|---|---|
| Name | `EQMU_updateEntitlementPBL` |
| URL expression | `="https://eqm-utility.fly.dev/entitlements/" & ri!entitlementId` |
| Method | PATCH |
| Body | JSON: `={"pbl_description": ri!pblDescription}` (use the expression mode for the body; Appian will serialize the dictionary to JSON) |
| Headers | `Authorization: Bearer <token>` (inherited from the connected system) |
| Usage | Modifies data |

- [ ] **Step 2: Add rule inputs**

- `entitlementId` (Text, Required)
- `pblDescription` (Text, Required)

- [ ] **Step 3: Test**

Set test values:
- `entitlementId`: a real entitlement ID
- `pblDescription`: `"Test update from Appian integration test"`

Click TEST.
Expected: response body shows the entitlement with the updated `pbl_description` field. Status 200.

- [ ] **Step 4: Save**

### Task 3.5: Create `EQMU_transitionViolation` integration

- [ ] **Step 1: New integration**

| Field | Value |
|---|---|
| Name | `EQMU_transitionViolation` |
| URL expression | `="https://eqm-utility.fly.dev/violations/" & ri!violationId & "/transition"` |
| Method | POST |
| Body | `={"target": ri!targetState}` |
| Headers | inherits bearer token |
| Usage | Modifies data |

- [ ] **Step 2: Rule inputs**

- `violationId` (Text, Required)
- `targetState` (Text, Required) — values like `"resolved"`, `"rejected"`, `"pending_approval"`

- [ ] **Step 3: Test**

Pick an open violation ID, set `targetState` to `"resolved"`. Click TEST.
Expected: status 200, response shows the violation with `workflow_state: "resolved"`.

⚠️ This actually mutates state — only run TEST against a violation you don't mind closing. If needed, transition it back manually afterward.

- [ ] **Step 4: Save**

### Task 3.6: Create `EQMU_runTick` integration

- [ ] **Step 1: New integration**

| Field | Value |
|---|---|
| Name | `EQMU_runTick` |
| URL | `https://eqm-utility.fly.dev/simulate/tick` |
| Method | POST |
| Body | none (empty body) |
| Headers | inherits bearer token |
| Usage | Modifies data |

- [ ] **Step 2: No rule inputs**

- [ ] **Step 3: Test**

Click TEST.
Expected: status 200, response is some summary of the tick (e.g., violation counts).

- [ ] **Step 4: Save**

### Task 3.7: Smoke check — call all five from Expression Editor

- [ ] **Step 1: Open any existing interface (e.g., `EQMU_HealthDashboard`) and use Test mode → Expression Editor**

- [ ] **Step 2: Test each integration call**

```
=rule!EQMU_getMyFindings(userId: cons!EQMU_DEMO_USER_ID)
```

Expected: body contains `"data"` array.

```
=rule!EQMU_getEntitlementById(entitlementId: "ENT-00001")
```

Expected: dictionary with entitlement fields.

(Skip testing the modify integrations from the editor — they were already verified via TEST in Tasks 3.4–3.6.)

---

## Phase 4: Appian site page configuration

### Task 4.1: Add the My Findings page to the EQMU Site

- [ ] **Step 1: Open the Site object → Pages section → click ADD PAGE**

- [ ] **Step 2: Configure**

| Field | Value |
|---|---|
| Title | My Findings |
| Web Address Identifier | `my-findings` |
| Type | Interface |
| Content | (set in Task 5 once `EQMU_MyFindings` exists; for now leave blank or pick a placeholder) |
| Page Width | Wide |
| Visibility | Always show |

Don't save yet — first complete Task 5.1 to create the interface, then come back to set Content here. Or save with a placeholder interface and return.

(If you must save now: pick `EQMU_HealthDashboard` as a temporary content stub and replace later.)

---

## Phase 5: `EQMU_MyFindings` interface

Build the interface incrementally — get each chunk rendering before adding the next. Each task is a standalone Appian SAIL save.

### Task 5.1: Create the interface skeleton with rule input

- [ ] **Step 1: Create new Interface in Appian Designer**

Name: `EQMU_MyFindings`
Description: `Per-user remediation dashboard with embedded PBL Evaluator.`

- [ ] **Step 2: Add rule input**

- Name: `demoUserId`
- Type: Text
- Required: no (defaults to empty; SAIL falls through to constant)

- [ ] **Step 3: Paste the skeleton SAIL**

```
a!localVariables(
  local!effectiveUserId: if(
    or(isnull(ri!demoUserId), len(ri!demoUserId) = 0),
    cons!EQMU_DEMO_USER_ID,
    ri!demoUserId
  ),
  local!findingsResponse: rule!EQMU_getMyFindings(userId: local!effectiveUserId),
  local!findings: a!fromJson(local!findingsResponse.result.body).data,

  a!sectionLayout(
    label: "My Findings",
    contents: {
      a!richTextDisplayField(
        value: {
          a!richTextItem(text: "User: ", style: "EMPHASIS"),
          a!richTextItem(text: local!effectiveUserId, style: "STRONG"),
          a!richTextItem(text: "  •  Findings: " & count(local!findings), style: "EMPHASIS")
        }
      )
    }
  )
)
```

- [ ] **Step 4: Save and use Preview**

Expected: page renders showing `User: EMP-XXXXX • Findings: N` where N matches what you saw in Task 1.5 Step 3.

- [ ] **Step 5: Wire the page Content field on the Site to point at this interface**

(Pick up where Task 4.1 left off.) On the Site object, edit the My Findings page and set Content to `EQMU_MyFindings`. Save.

In the Edit Page dialog, the Rule Inputs section should now list `demoUserId`. Set:
- **Encrypt URL parameters**: OFF
- **Enable in URLs** toggle for `demoUserId`: ON
- Default Value: empty

Click DONE. Click the blue SAVE button on the Site editor.

- [ ] **Step 6: Verify on the live site**

Open `https://resiliencytesting.appiancloud.com/suite/sites/entitlement-quality-monitor-ut/page/my-findings`

Expected: same line as in Step 4 — `User: EMP-XXXXX • Findings: N`. The default user is `cons!EQMU_DEMO_USER_ID`.

Then try `…?demoUserId=EMP-00010` — `User: EMP-00010` should display.

### Task 5.2: Add KPI cards (Open / Pending / Resolved)

- [ ] **Step 1: Replace the SAIL with the KPI version**

```
a!localVariables(
  local!effectiveUserId: if(
    or(isnull(ri!demoUserId), len(ri!demoUserId) = 0),
    cons!EQMU_DEMO_USER_ID,
    ri!demoUserId
  ),
  local!findingsResponse: rule!EQMU_getMyFindings(userId: local!effectiveUserId, includeAll: true),
  local!findings: a!fromJson(local!findingsResponse.result.body).data,

  local!filterStage: null,

  local!openCount: sum(a!forEach(items: local!findings, expression: if(tostring(index(fv!item, "status", "")) = "Open", 1, 0))),
  local!pendingCount: sum(a!forEach(items: local!findings, expression: if(tostring(index(fv!item, "status", "")) = "Pending Approval", 1, 0))),
  local!resolvedCount: sum(a!forEach(items: local!findings, expression: if(tostring(index(fv!item, "status", "")) = "Resolved", 1, 0))),

  a!sectionLayout(
    label: "My Findings",
    contents: {
      a!richTextDisplayField(
        value: {
          a!richTextItem(text: "User: ", style: "EMPHASIS"),
          a!richTextItem(text: local!effectiveUserId, style: "STRONG")
        },
        marginBelow: "STANDARD"
      ),
      a!columnsLayout(
        columns: {
          a!columnLayout(contents: {
            a!cardLayout(
              contents: a!richTextDisplayField(value: {
                a!richTextItem(text: "Open", size: "MEDIUM_PLUS", style: "STRONG"),
                char(10),
                a!richTextItem(text: tostring(local!openCount), size: "LARGE_PLUS")
              }),
              style: if(local!filterStage = "Open", "ACCENT", "WARN"),
              link: a!dynamicLink(
                saveInto: a!save(local!filterStage, if(local!filterStage = "Open", null, "Open"))
              ),
              showShadow: true
            )
          }),
          a!columnLayout(contents: {
            a!cardLayout(
              contents: a!richTextDisplayField(value: {
                a!richTextItem(text: "Pending Approval", size: "MEDIUM_PLUS", style: "STRONG"),
                char(10),
                a!richTextItem(text: tostring(local!pendingCount), size: "LARGE_PLUS")
              }),
              style: if(local!filterStage = "Pending Approval", "ACCENT", "STANDARD"),
              link: a!dynamicLink(
                saveInto: a!save(local!filterStage, if(local!filterStage = "Pending Approval", null, "Pending Approval"))
              ),
              showShadow: true
            )
          }),
          a!columnLayout(contents: {
            a!cardLayout(
              contents: a!richTextDisplayField(value: {
                a!richTextItem(text: "Resolved", size: "MEDIUM_PLUS", style: "STRONG"),
                char(10),
                a!richTextItem(text: tostring(local!resolvedCount), size: "LARGE_PLUS")
              }),
              style: if(local!filterStage = "Resolved", "ACCENT", "SUCCESS"),
              link: a!dynamicLink(
                saveInto: a!save(local!filterStage, if(local!filterStage = "Resolved", null, "Resolved"))
              ),
              showShadow: true
            )
          })
        }
      )
    }
  )
)
```

Note: the rule call now passes `includeAll: true` so resolved findings are visible for the Resolved KPI count. Update the integration's URL builder to add a `&include_all=true` query parameter, OR add a second rule input on `EQMU_getMyFindings` and pass it through. The simplest: edit the integration's Query Parameters list to add `include_all` mapped to a new `includeAll` Boolean rule input (default false), and pass `true` from this SAIL.

- [ ] **Step 2: Save and reload the live page**

Expected: three KPI cards row showing Open / Pending Approval / Resolved counts. Clicking a card highlights it (changes to ACCENT style); clicking again deselects.

- [ ] **Step 3: Commit (none — Appian saves are not git-tracked. This is a checkpoint reminder.)**

### Task 5.3: Add the filterable findings grid

- [ ] **Step 1: Extend the SAIL with `local!filteredFindings` and a grid**

After `local!resolvedCount`, add:

```
local!filteredFindings: if(
  isnull(local!filterStage),
  local!findings,
  reject(
    fn!isnull,
    a!forEach(
      items: local!findings,
      expression: if(
        tostring(index(fv!item, "status", "")) = local!filterStage,
        fv!item,
        null
      )
    )
  )
),
local!selectedViolationId: null,
```

Then in the section's `contents:` array, after the columnsLayout closing `}` (before the section's closing `}`), add a comma and:

```
a!gridField(
  label: "Findings (" & count(local!filteredFindings) & ")",
  labelPosition: "ABOVE",
  data: local!filteredFindings,
  columns: {
    a!gridColumn(
      label: "Violation",
      value: a!linkField(
        links: a!dynamicLink(
          label: tostring(index(fv!row, "violationId", "")),
          saveInto: a!save(
            local!selectedViolationId,
            if(
              local!selectedViolationId = tostring(index(fv!row, "violationId", "")),
              null,
              tostring(index(fv!row, "violationId", ""))
            )
          )
        )
      ),
      width: "NARROW"
    ),
    a!gridColumn(label: "Rule", value: index(fv!row, "ruleName", "")),
    a!gridColumn(label: "Severity", value: index(fv!row, "severity", "")),
    a!gridColumn(label: "Status", value: index(fv!row, "status", "")),
    a!gridColumn(
      label: "Target",
      value: tostring(index(fv!row, "targetType", "")) & " — " & tostring(index(fv!row, "targetId", ""))
    ),
    a!gridColumn(label: "Recommended Action", value: index(fv!row, "recommendedAction", ""))
  },
  pageSize: 25,
  emptyGridMessage: "No findings match the current filter."
)
```

- [ ] **Step 2: Save and reload the live page**

Expected: a 6-column grid renders below the KPI cards. Clicking a Violation ID toggles the row selection (state-only — no visible change yet, drill-down panel is the next task).

### Task 5.4: Add the drill-down panel — non-PBL branch first

The non-PBL branch is simpler (no iframe). Build it first, verify, then layer on the PBL branch.

- [ ] **Step 1: Add the selectedFinding derived local**

After `local!selectedViolationId`:

```
local!selectedFinding: if(
  isnull(local!selectedViolationId),
  null,
  index(
    reject(
      fn!isnull,
      a!forEach(
        items: local!findings,
        expression: if(
          tostring(index(fv!item, "violationId", "")) = local!selectedViolationId,
          fv!item,
          null
        )
      )
    ),
    1,
    null
  )
),
local!isPblFinding: if(
  isnull(local!selectedFinding),
  false,
  contains(
    {"PBL completeness", "PBL template match"},
    tostring(index(local!selectedFinding, "ruleName", ""))
  )
),
local!busy: false,
```

- [ ] **Step 2: Add the drill-down panel after the grid**

Inside the section's `contents:` array, after the gridField's closing `)`, add a comma and:

```
if(
  isnull(local!selectedFinding),
  {},
  if(
    local!isPblFinding,
    /* PBL branch — built in Task 5.5 */
    a!cardLayout(
      contents: a!richTextDisplayField(
        value: a!richTextItem(text: "PBL drill-down — built in next task.", style: "EMPHASIS")
      ),
      style: "INFO"
    ),
    /* Non-PBL branch */
    a!cardLayout(
      contents: {
        a!richTextDisplayField(
          value: {
            a!richTextItem(text: tostring(index(local!selectedFinding, "ruleName", "")), size: "MEDIUM", style: "STRONG"),
            char(10),
            a!richTextItem(text: "Severity: " & tostring(index(local!selectedFinding, "severity", "")) & "    Status: " & tostring(index(local!selectedFinding, "status", "")), style: "EMPHASIS")
          },
          marginBelow: "STANDARD"
        ),
        a!columnsLayout(
          columns: {
            a!columnLayout(contents: {
              a!textField(label: "Target", readOnly: true, value: tostring(index(local!selectedFinding, "targetType", "")) & " — " & tostring(index(local!selectedFinding, "targetId", ""))),
              a!textField(label: "Detected At", readOnly: true, value: tostring(index(local!selectedFinding, "detectedAt", "")))
            }),
            a!columnLayout(contents: {
              a!textField(label: "Recommended Action", readOnly: true, value: tostring(index(local!selectedFinding, "recommendedAction", "")))
            })
          }
        ),
        a!paragraphField(
          label: "Reason",
          readOnly: true,
          value: tostring(index(local!selectedFinding, "reason", "")),
          height: "SHORT"
        ),
        a!buttonArrayLayout(
          align: "START",
          marginAbove: "STANDARD",
          buttons: {
            a!buttonWidget(
              label: "Mark as Resolved",
              icon: "check",
              style: "SOLID",
              disabled: local!busy,
              saveInto: {
                a!save(local!busy, true),
                rule!EQMU_transitionViolation(
                  violationId: tostring(index(local!selectedFinding, "violationId", "")),
                  targetState: "resolved"
                ),
                a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
                a!save(local!selectedViolationId, null),
                a!save(local!busy, false)
              }
            ),
            a!buttonWidget(
              label: "Re-evaluate Now",
              icon: "refresh",
              style: "OUTLINE",
              disabled: local!busy,
              saveInto: {
                a!save(local!busy, true),
                rule!EQMU_runTick(),
                a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
                a!save(local!busy, false)
              }
            ),
            a!buttonWidget(
              label: "Cancel",
              icon: "times",
              style: "GHOST",
              saveInto: a!save(local!selectedViolationId, null)
            )
          }
        )
      },
      style: "STANDARD",
      showShadow: true,
      marginAbove: "STANDARD"
    )
  )
)
```

- [ ] **Step 3: Save and reload**

Expected:
- Click a non-PBL finding's violation ID in the grid → drill-down card appears below with rule name, severity, status, target, action, reason, and three buttons.
- Click **Cancel** → drill-down clears.
- Click **Mark as Resolved** on a real open finding → the violation is transitioned, the grid refreshes, and that row is gone (or moves to Resolved if filter is set there).
- Click **Re-evaluate Now** → tick runs, grid refreshes (might not change anything if no underlying issue was fixed).

⚠️ The Mark Resolved button mutates state. Test on a finding you don't mind closing; you can manually re-open it via `POST /violations/{vid}/reopen` if needed.

### Task 5.5: Add the PBL branch with iframe and write-back

- [ ] **Step 1: Add the entitlement-fetch local for the selected entitlement**

After `local!isPblFinding`:

```
local!selectedEntitlementId: if(
  isnull(local!selectedFinding),
  null,
  if(
    tostring(index(local!selectedFinding, "targetType", "")) = "entitlement",
    tostring(index(local!selectedFinding, "targetId", "")),
    null
  )
),
local!entitlementResponse: if(
  isnull(local!selectedEntitlementId),
  null,
  rule!EQMU_getEntitlementById(entitlementId: local!selectedEntitlementId)
),
local!selectedEntitlement: if(
  isnull(local!entitlementResponse),
  null,
  a!fromJson(local!entitlementResponse.result.body)
),
local!rewrittenPbl: "",
```

- [ ] **Step 2: Add a small URL-encoder helper**

Create a new Expression Rule in Appian Designer: `EQMU_urlEncode`.

Rule input: `text` (Text)

Expression body:

```
substitute(
  substitute(
    substitute(
      substitute(
        substitute(
          tostring(ri!text),
          "%", "%25"
        ),
        "&", "%26"
      ),
      "#", "%23"
    ),
    "+", "%2B"
  ),
  " ", "%20"
)
```

Note: Order matters — encode `%` first, before any other substitution introduces `%` characters. Save.

- [ ] **Step 3: Replace the PBL branch placeholder with the real iframe + form**

Find the placeholder `"PBL drill-down — built in next task."` block and replace the whole `if(local!isPblFinding, ...)` true-branch with:

```
a!cardLayout(
  contents: {
    a!richTextDisplayField(
      value: {
        a!richTextItem(text: tostring(index(local!selectedFinding, "ruleName", "")), size: "MEDIUM", style: "STRONG"),
        char(10),
        a!richTextItem(text: "Entitlement: " & tostring(index(local!selectedEntitlement, "name", "")) & "  •  Severity: " & tostring(index(local!selectedFinding, "severity", "")), style: "EMPHASIS"),
        char(10),
        a!richTextItem(text: tostring(index(local!selectedFinding, "reason", "")), style: "EMPHASIS")
      },
      marginBelow: "STANDARD"
    ),
    a!webContentField(
      label: "Rewrite the PBL using the embedded evaluator",
      url: cons!EQMU_PBL_EVALUATOR_URL & "?" &
        "name=" & rule!EQMU_urlEncode(text: tostring(index(local!selectedEntitlement, "name", ""))) & "&" &
        "description=" & rule!EQMU_urlEncode(text: tostring(index(local!selectedEntitlement, "pbl_description", ""))) & "&" &
        "resourceType=entitlement" & "&" &
        "resourceName=" & rule!EQMU_urlEncode(text: tostring(index(local!selectedEntitlement, "name", "")))
      ,
      height: "TALL"
    ),
    a!paragraphField(
      label: "Rewritten PBL Description",
      labelPosition: "ABOVE",
      instructions: "Copy your improved PBL from the evaluator above and paste it here, then click Save & Re-evaluate.",
      value: local!rewrittenPbl,
      saveInto: local!rewrittenPbl,
      height: "SHORT"
    ),
    a!buttonArrayLayout(
      align: "START",
      marginAbove: "STANDARD",
      buttons: {
        a!buttonWidget(
          label: "Save & Re-evaluate",
          icon: "save",
          style: "SOLID",
          disabled: or(local!busy, len(local!rewrittenPbl) = 0),
          saveInto: {
            a!save(local!busy, true),
            rule!EQMU_updateEntitlementPBL(
              entitlementId: tostring(index(local!selectedEntitlement, "id", "")),
              pblDescription: local!rewrittenPbl
            ),
            rule!EQMU_runTick(),
            a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
            a!save(local!selectedViolationId, null),
            a!save(local!rewrittenPbl, ""),
            a!save(local!busy, false)
          }
        ),
        a!buttonWidget(
          label: "Cancel",
          icon: "times",
          style: "GHOST",
          saveInto: {
            a!save(local!selectedViolationId, null),
            a!save(local!rewrittenPbl, "")
          }
        )
      }
    )
  },
  style: "INFO",
  showShadow: true,
  marginAbove: "STANDARD"
)
```

- [ ] **Step 4: Save and reload the live page**

Expected:
- Click a PBL finding's violation ID in the grid → drill-down renders with:
  - Rule name + entitlement name + severity + reason text
  - Embedded PBL Evaluator iframe (TALL height) showing the Evaluate page with Name, Description, Resource Name pre-populated from the selected entitlement
  - Empty "Rewritten PBL Description" textarea
  - Save & Re-evaluate (disabled — textarea empty) and Cancel buttons

- [ ] **Step 5: End-to-end test**

In the iframe, type a longer/clearer PBL description in the description field, scroll down and click "Submit" inside the iframe. The evaluator should produce a score.

Then in the Appian textarea below the iframe, paste the improved PBL text. The Save & Re-evaluate button should activate.

Click **Save & Re-evaluate**. Expected: button shows busy state briefly, then the drill-down clears, the grid refreshes, and the PBL finding is gone (because the rule no longer fires against the new description).

⚠️ This actually mutates the entitlement on EQM. Pick a test entitlement; you can revert manually via `PATCH /entitlements/{id}` if needed.

### Task 5.6: Add the empty / error states

- [ ] **Step 1: Add an empty-state block at the top of `contents:`**

Replace the section's `contents:` array opening to render the empty state when there are no findings, before the KPI cards. Wrap the whole section body in:

```
contents: if(
  count(local!findings) = 0,
  {
    a!cardLayout(
      contents: a!richTextDisplayField(
        value: {
          a!richTextItem(text: "✓ No active findings", size: "MEDIUM_PLUS", style: "STRONG", color: "POSITIVE"),
          char(10),
          a!richTextItem(text: "User " & local!effectiveUserId & " has a clean access posture.", style: "EMPHASIS")
        }
      ),
      style: "SUCCESS",
      showShadow: true
    )
  },
  {
    /* — existing contents from Tasks 5.1 through 5.5 — paste them here —  */
  }
)
```

- [ ] **Step 2: Verify by switching to a user with no findings**

Find a clean user (one with `assignmentsWithFindings`-style score 0) — or simply test with a made-up ID like `?demoUserId=EMP-NONEXISTENT`. Expected: empty-state card shows.

- [ ] **Step 3: Add an integration error catch (optional defensive)**

Wrap the `local!findings` derivation in a `if(local!findingsResponse.success, ..., null)` guard if you want a graceful "API unreachable" surface. For the demo, the existing behavior (Appian shows a red error bar at the top) is acceptable. Defer.

---

## Phase 6: End-to-end demo verification

### Task 6.1: Full demo walkthrough

- [ ] **Step 1: Reset the simulator to a known state**

```bash
curl -X POST -H "Authorization: Bearer $(flyctl secrets list --json --app eqm-utility 2>/dev/null | python3 -c "import sys, json; [print(s['Name']) for s in json.load(sys.stdin)]")" \
  https://eqm-utility.fly.dev/simulate/reset
```

(Or use the UI button on the Fly dashboard at https://eqm-utility.fly.dev/.)

- [ ] **Step 2: Inject the `bad_pbl_batch` scenario**

Trigger from the Fly dashboard or via curl with the bearer token. This guarantees PBL findings exist.

- [ ] **Step 3: Open the live My Findings page**

`https://resiliencytesting.appiancloud.com/suite/sites/entitlement-quality-monitor-ut/page/my-findings`

Verify:
- KPI cards show counts > 0
- Grid lists the user's findings
- Click a non-PBL finding → drill-down shows details + Mark Resolved button
- Click a PBL finding → drill-down shows iframe + paragraph field + Save button (disabled)
- Type in the paragraph field → Save button activates
- Click Save & Re-evaluate → grid refreshes, finding is gone

- [ ] **Step 4: Verify URL parameter persona switching**

Change the URL to `…/page/my-findings?demoUserId=EMP-00010`. Verify:
- The user identifier text reflects the new ID
- The grid shows that user's findings (different content from the default)

- [ ] **Step 5: Update memory with the completed feature**

Save the My Findings deployment as a project memory entry (URL, demo persona ID, embedded PBL Evaluator URL) so future sessions pick up cleanly.

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| EQM `/api/user-findings` endpoint | Phase 1, Tasks 1.1–1.5 |
| PBL Evaluator URL params | Phase 2, Task 2.1 |
| Two constants | Phase 3, Task 3.1 |
| Five integrations | Phase 3, Tasks 3.2–3.6 |
| Site page configuration | Phase 4, Task 4.1 + Task 5.1 Step 5 |
| SAIL: rule input + skeleton | Task 5.1 |
| SAIL: KPI cards | Task 5.2 |
| SAIL: filterable grid | Task 5.3 |
| SAIL: drill-down panel — non-PBL | Task 5.4 |
| SAIL: drill-down panel — PBL with iframe + write-back | Task 5.5 |
| SAIL: empty state | Task 5.6 |
| Demo persona switching | Task 6.1 Step 4 |
| Iframe feasibility risk | Phase 0 (de-risked first) |

**Placeholder scan:** The plan contains `EMP-XXXXX` and `<token>` as labeled placeholders that get filled in during execution (Tasks 1.5 and 3.4 explicitly substitute real values). No "TODO" / "TBD" / "fill in later" left.

**Type consistency:** Rule input names match across integrations and SAIL — `userId`, `entitlementId`, `pblDescription`, `violationId`, `targetState`. Constant names match across SAIL — `cons!EQMU_DEMO_USER_ID`, `cons!EQMU_PBL_EVALUATOR_URL`. Local variable names match across the incremental SAIL builds — `local!effectiveUserId`, `local!findingsResponse`, `local!findings`, `local!filterStage`, `local!filteredFindings`, `local!selectedViolationId`, `local!selectedFinding`, `local!isPblFinding`, `local!selectedEntitlementId`, `local!entitlementResponse`, `local!selectedEntitlement`, `local!rewrittenPbl`, `local!busy`.

**Scope check:** Single feature, one implementation plan. Each phase is self-contained and produces a verifiable deliverable (Phase 1 endpoint, Phase 2 deployed PBL Evaluator update, Phase 3 working integrations, Phase 5 progressive interface).
