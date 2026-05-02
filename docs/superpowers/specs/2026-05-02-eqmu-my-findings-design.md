# Design: EQMU "My Findings" Per-User Remediation Interface

**Date:** 2026-05-02
**Status:** Approved with iframe→new-tab pivot (Phase 0 spike confirmed Appian Cloud's platform CSP blocks third-party iframes)
**Owner:** zdjimas

## Overview

Add a per-user remediation experience to the EQMU Appian site so that any logged-in user can see violations touching them and fix them in place — including a one-click launcher to PBL Evaluator (opens in a new browser tab pre-populated with the entitlement under remediation) for rewriting low-quality entitlement descriptions, plus generic resolution actions for non-PBL findings.

**Iframe pivot note:** Original design embedded PBL Evaluator via `a!webContentField`. Phase 0 spike confirmed Appian Cloud's platform-level CSP blocks third-party iframes regardless of tenant config (curl confirmed PBL Evaluator sends no `X-Frame-Options` headers, so the block originates from Appian's parent frame). Pivoted to `a!safeLink` opening in a new tab. The user works in the new tab then alt-tabs back to Appian to paste the rewritten PBL and submit.

For this iteration we ship as a **single-user demo**: a SAIL constant pins one EQM employee, an optional `?demoUserId=EMP-XXXXX` URL parameter overrides it for switching demo personas mid-presentation. Real Appian-user-to-EQM-employee mapping is deferred.

## Goals

- Add a new "My Findings" page to the existing EQMU Appian Site, alongside Dashboard / Remediation / Finding Detail.
- Filter findings to those touching the demo user (direct user-targeted findings + findings on assignments and entitlements they hold).
- Provide a one-click "Open PBL Evaluator" launcher (`a!safeLink`, new tab) pre-populated via URL parameters with the entitlement under remediation.
- Support write-back from the user dashboard: PATCH the entitlement's `pbl_description`, trigger a rule-engine tick, and refresh findings so resolved violations clear in the UI.
- Provide a generic "Mark as Resolved" / "Re-evaluate Now" action for non-PBL findings.

## Non-goals

- Real per-user authentication or mapping from Appian's `loggedInUser()` to EQM employees. Deferred to a follow-up.
- Round-trip integration where PBL Evaluator writes directly to EQM (cross-app CORS + postMessage handshake). The user reviews and submits via Appian.
- Per-rule custom remediation forms beyond the PBL flow. Other finding types use the generic resolution buttons for now.
- Persistence of in-progress PBL drafts. If the user navigates away mid-edit, their draft is lost.

## Architecture

### High-level data flow

```
Appian Site → /page/my-findings?demoUserId=EMP-XXXXX (optional)
  ↓
EQMU_MyFindings interface (SAIL)
  ↓ rule!EQMU_getMyFindings(userId)
EQM (Fly): GET /api/user-findings?userId=EMP-XXXXX
  ↓ joins findings → assignments → user, returns list
SAIL renders KPI cards, filterable grid, drill-down panel
  ↓ user clicks a row → local!selectedViolationId set
  ↓ if PBL finding: rule!EQMU_getEntitlementById(entId)
SAIL drill-down panel:
  - PBL: a!safeLink "Open PBL Evaluator" (new tab, params prefilled)
         + textarea + "Save & Re-evaluate" button
  - Non-PBL: read-only details + "Mark as Resolved" + "Re-evaluate Now"
  ↓ on action button click
EQM: PATCH /entitlements/{id} → POST /simulate/tick → POST /violations/{vid}/transition
  ↓ a!refreshVariable(local!findingsResponse)
SAIL re-renders; resolved findings disappear or show new state
```

### Components

1. **EQM Fly backend** — one new GET endpoint
2. **PBL Evaluator frontend** — one component update (URL parameter pre-population on Evaluate page)
3. **Appian** — five new integrations, two new constants, one new interface, one new Site page

## EQM Fly backend changes

Add `GET /api/user-findings?userId={id}` to `src/eqm/api.py`. Returns the same Appian-friendly shape as `/api/flagged-records` (a `{"data": [...]}` envelope of `_project_violation` outputs). Filtered to violations touching the user across three categories, unioned and deduplicated by `id`:

1. `target_type=user AND target_id=userId` — direct user findings
2. `target_type=assignment AND assignment.employee_id=userId` — findings on the user's assignments
3. `target_type=entitlement AND entitlement_id IN (assignments where employee_id=userId AND active=true)` — findings on entitlements the user holds

Open (no auth) — same posture as `/api/flagged-records`. Bearer-token-gated reads were never adopted for the existing reads.

Excludes resolved/rejected violations by default (mirrors `include_all=false` behavior on the existing endpoint). Optional `include_all=true` query parameter for parity.

## PBL Evaluator frontend changes

Modify `frontend/src/pages/Evaluate.tsx` to read these URL query parameters on mount and pre-populate the form's initial state:

- `name`
- `description`
- `resourceType`
- `resourceName`
- `accessLevel`
- `conditions`
- `businessJustification`

Use `useSearchParams` from `react-router-dom` v7. If a parameter is absent, leave the field empty as today. No CORS or CSP changes — the iframe is same-origin static content; Appian's iframe loads it as-is.

After changes, redeploy via `flyctl deploy` from the PBL-Evaluator repo root.

## Appian — constants

| Constant | Type | Value |
|---|---|---|
| `cons!EQMU_DEMO_USER_ID` | Text | `"EMP-00001"` (pick an employee with a varied finding portfolio) |
| `cons!EQMU_PBL_EVALUATOR_URL` | Text | `"https://pbl-evaluator.fly.dev/evaluate"` |

## Appian — integrations

All five use the existing `EQMU Fly Backend API` connected system; the bearer token is already wired for write endpoints.

| Name | Type | Method | Endpoint | Notes |
|---|---|---|---|---|
| `EQMU_getMyFindings` | Query | GET | `/api/user-findings?userId={!userId}` | Per-user findings |
| `EQMU_getEntitlementById` | Query | GET | `/entitlements/{!entitlementId}` | Pre-populate iframe |
| `EQMU_updateEntitlementPBL` | Modify | PATCH | `/entitlements/{!entId}` | Body: `{"pbl_description": "{!pbl}"}` |
| `EQMU_transitionViolation` | Modify | POST | `/violations/{!vid}/transition` | Body: `{"target": "resolved"}` |
| `EQMU_runTick` | Modify | POST | `/simulate/tick` | Empty body |

Per established pattern in this tenant: use full URLs in the integration "URL" field, not connected-system path templates with `{!variable}` substitution — Appian HTTP-only mode is unreliable with path placeholders. Build the path-with-id strings in SAIL and pass the full URL.

## Appian — Site page

| Field | Value |
|---|---|
| Title | My Findings |
| Web Address Identifier | `my-findings` |
| Type | Interface |
| Content | `EQMU_MyFindings` |
| Page Width | Wide |
| Visibility | Always show (toggle to "Only when…" later for role gating) |

Rule input configuration:

- `demoUserId` (Text) — **Encrypt URL parameters: OFF, Enable in URLs: ON** (saved gotcha — without these two settings, query parameters silently drop)
- Default value: empty (so falls through to `cons!EQMU_DEMO_USER_ID` in the SAIL)

## Appian — interface (`EQMU_MyFindings`)

### Rule input

- `demoUserId` (Text) — populated by the URL query parameter, may be empty

### Local variables

```
local!effectiveUserId: if(or(isnull(ri!demoUserId), len(ri!demoUserId)=0),
                          cons!EQMU_DEMO_USER_ID,
                          ri!demoUserId)

local!findingsResponse: rule!EQMU_getMyFindings(userId: local!effectiveUserId),
local!findings:         a!fromJson(local!findingsResponse.result.body).data,

local!filterStage:        null,    /* Open / Pending Approval / Resolved */
local!selectedViolationId: null,
local!rewrittenPbl:        "",
local!busy:                false,
```

Derived locals (computed from `local!findings`):
- `local!openCount`, `local!pendingCount`, `local!resolvedCount` for KPI cards
- `local!filteredFindings` after applying `local!filterStage`
- `local!selectedFinding` — the row matching `local!selectedViolationId`
- `local!isPblFinding` — true when the selected finding's `ruleName` is `"PBL completeness"` or `"PBL template match"`
- `local!selectedEntitlement` — populated only when a PBL finding is selected, via `EQMU_getEntitlementById`

### Layout

```
SectionLayout "My Findings"
├── Filter status row + "Reset filters" button (mirrors RemediationDashboard pattern)
├── KPI cards row (3 cards, clickable to filter): Open, Pending Approval, Resolved
├── Grid (filterable)
│   columns: Violation ID (link), Rule, Severity, Status, Target, Recommended Action
│   pageSize: 25
└── Drill-down panel (only when local!selectedViolationId is set)
    ├── Header: rule name, severity tag, recommendation text
    ├── If PBL finding:
    │   ├── a!safeLink "Open PBL Evaluator in new tab" (URL with entitlement params)
    │   ├── a!paragraphField "Rewritten PBL Description"
    │   └── Buttons: [Save & Re-evaluate] (SOLID, primary) [Cancel] (GHOST)
    └── If non-PBL finding:
        ├── Read-only details (target, detectedAt, reason, evidence)
        └── Buttons: [Mark as Resolved] (SOLID) [Re-evaluate Now] (OUTLINE) [Cancel] (GHOST)
```

### Launcher URL construction

```
cons!EQMU_PBL_EVALUATOR_URL & "?" &
  "name="                  & rule!EQMU_urlEncode(index(local!selectedEntitlement, "name", "")) & "&" &
  "description="           & rule!EQMU_urlEncode(index(local!selectedEntitlement, "pbl_description", "")) & "&" &
  "resourceType=entitlement&" &
  "resourceName="          & rule!EQMU_urlEncode(index(local!selectedEntitlement, "name", ""))
```

Wrapped in `a!safeLink(uri: ..., openLinkIn: "NEW_TAB")` and rendered as a clickable link inside the drill-down panel ("Open PBL Evaluator with this entitlement →").

`urlencode()` not present natively in Appian SAIL — defined as a small expression rule `EQMU_urlEncode(text)` using a chain of `substitute()` calls for `% & # + space` (encode `%` first to avoid double-encoding).

### Save & Re-evaluate flow (PBL branch)

Button `saveInto` chain:

```
{
  a!save(local!busy, true),
  rule!EQMU_updateEntitlementPBL(
    entId: index(local!selectedEntitlement, "id", ""),
    pbl: local!rewrittenPbl
  ),
  rule!EQMU_runTick(),
  a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
  a!save(local!selectedViolationId, null),
  a!save(local!rewrittenPbl, ""),
  a!save(local!busy, false)
}
```

Button is disabled when `local!busy = true` OR `len(local!rewrittenPbl) = 0`.

### Mark as Resolved flow (non-PBL branch)

```
{
  a!save(local!busy, true),
  rule!EQMU_transitionViolation(
    vid: tostring(index(local!selectedFinding, "violationId", "")),
    target: "resolved"
  ),
  a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
  a!save(local!selectedViolationId, null),
  a!save(local!busy, false)
}
```

### Re-evaluate Now flow (non-PBL branch)

```
{
  a!save(local!busy, true),
  rule!EQMU_runTick(),
  a!refreshVariable(value: local!findingsResponse, refreshAlways: true),
  a!save(local!busy, false)
}
```

### Empty / error states

- **No findings for user:** card with `style: "SUCCESS"`, message `"✓ No active findings — your access posture is clean."`
- **`getMyFindings` integration error:** `style: "ERROR"` card with message and a "Retry" button that calls `a!refreshVariable(local!findingsResponse, refreshAlways: true)`
- **Save & Re-evaluate fails:** `local!rewrittenPbl` retained (drill-down stays open); error card surfaces; `local!busy` cleared
- **Mark as Resolved fails:** error card; selection retained
- **No `selectedEntitlement`** when PBL finding selected (lookup returned null): drill-down shows error card with "Could not load entitlement" and a Cancel button

## Demo persona switching

To switch the demoed user mid-presentation, edit the URL: `…/page/my-findings?demoUserId=EMP-00042`. The SAIL falls through to the URL param when present. No SAIL change needed.

For the demo, pre-pick 2–3 employees that have a mix of finding types so that switching gives a varied story.

## Open questions / risks

- **`urlencode` in SAIL:** Appian doesn't have a native function. Mitigation is a small expression rule `EQMU_urlEncode` using `substitute()` chains for `%`, `&`, `#`, `+`, space (encode `%` first to avoid double-encoding).
- **Tick timing:** `POST /simulate/tick` is synchronous in the current EQM implementation; the rule engine runs on the request thread. If runtime grows past ~5s for any reason, Appian's integration timeout (10s default) might fire. Current runs are sub-second.
- **Demo user selection:** EMP-00001 may not have varied findings. Verify before locking the constant. Document the chosen employee's profile in the README.
- **Multiple PBL findings on the same entitlement:** if a user has both "PBL completeness" and "PBL template match" on the same entitlement, fixing the PBL once should clear both on the next tick. Verify this is the case.

## Resolved issues (Phase 0 spike findings)

- **Iframe block (RESOLVED):** Appian Cloud's platform-level CSP blocks third-party iframes via `a!webContentField` regardless of tenant config. Confirmed via test embed of `https://pbl-evaluator.fly.dev/` — the field rendered blank with no useful content. PBL Evaluator's nginx sends no `X-Frame-Options` headers (verified via curl), so the block is on Appian's side. The "Embedded Interfaces" admin setting controls embedding Appian INTO external apps (the opposite direction), not the iframe allow-list. Pivoted to `a!safeLink` opening in a new browser tab.

## Out of scope (saved for later iterations)

- Real Appian-user → EQM-employee mapping (email-based or constant lookup table)
- PBL Evaluator → EQM direct write-back (round-trip integration)
- Per-rule custom remediation forms beyond PBL
- Multi-user demos with shared/isolated state (currently per-browser via PBL Evaluator's localStorage)
- Approval workflow for sensitive fixes (e.g., entitlement description changes that touch admin tiers)
- Audit log surfaced in the UI (changes are tracked server-side via violation workflow_history)
