# Entitlement Quality Monitor Utility

A simulated **Data Fabric** for entitlement governance, designed to be consumed by **Appian** as a Connected System. Generates and continuously mutates dummy entitlement / HR / CMDB records, runs a deterministic, fact-based **rules engine** over them, and emits violations with concrete suggested fixes — all gated by a human-in-the-loop workflow state machine.

The rules engine is **strictly deterministic**: no LLM, no fuzzy matching. Every rule is a pure Python function with unit tests. That's the Model Risk Management posture this tool exists to demonstrate.

## What's in here

- **`data/`** — JSON files that ARE the data fabric (entitlements, HR, CMDB, assignments, violations). Version-controlled audit trail.
- **`src/eqm/rules/`** — 13 deterministic rules across four categories.
- **`src/eqm/engine.py`** — runs all rules; reconciles new findings against existing violations to preserve Appian-side workflow state.
- **`src/eqm/simulator.py`** — drift mode: random, mostly-realistic mutations every 30 min via GitHub Actions.
- **`src/eqm/scenarios.py`** — seven on-cue demo scenarios (e.g. `terminated_user_with_admin`, `sod_payment_breach`).
- **`src/eqm/api.py`** — FastAPI app with read/write/simulate/sync endpoints + an HTML dashboard at `/`.
- **`fly.toml`, `Dockerfile`, `scripts/deploy.sh`** — Fly.io deployment.

## Quickstart (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export EQM_BEARER_TOKEN=demo-token
export EQM_DATA_DIR=./data

python -m eqm seed --small
python -m eqm drift
python -m eqm scenario kitchen_sink

uvicorn eqm.api:app --reload --port 8080
# open http://localhost:8080
```

## Tests

```bash
pytest -q
ruff check src tests
```

Every rule has its own unit test file under `tests/rules/`. Adding a 14th rule = drop a file in `src/eqm/rules/`, register it, write a test.

## The 13 rules

| ID | Rule | Severity |
|---|---|---|
| ENT-Q-01 | PBL completeness | LOW |
| ENT-Q-02 | PBL template match | MEDIUM |
| ENT-Q-03 | Tier vs role coherence | HIGH |
| ENT-Q-04 | Division-resource coherence | HIGH |
| TOX-01 | Maker-checker conflict | CRITICAL |
| TOX-02 | Dev + Prod-Admin same app | CRITICAL |
| TOX-03 | Tier-1 in 3+ divisions | HIGH |
| HR-01 | Role mismatch | MEDIUM |
| HR-02 | Division mismatch | MEDIUM |
| HR-03 | Legacy entitlement (≥30d post-role-change) | HIGH |
| HR-04 | Terminated user holds active assignment | CRITICAL |
| CMDB-01 | Orphan entitlement | LOW |
| CMDB-02 | Tier inconsistency on critical resource | HIGH |

## Workflow state machine

```
OPEN → PENDING_APPROVAL → APPROVED → RESOLVED
                       → REJECTED   (terminal — suppresses re-detection)
                       → MANUAL_REPAIR → RESOLVED

REJECTED → OPEN  (only via POST /violations/{id}/reopen, compliance-driven)
```

Every transition appends an entry to `workflow_history` capturing the actor, timestamp, note, and any `override_fix`.

## Appian Connector setup

Once deployed to Fly (or any HTTPS host), wire Appian like this:

1. **Connected System** (HTTP, Bearer auth)
   - Base URL: `https://eqm-utility.fly.dev`
   - Auth: `Authorization: Bearer ${EQM_BEARER_TOKEN}`

2. **Integrations** — create one per endpoint Appian needs:
   - `GET /violations?state=open&severity=critical` — main poll
   - `POST /violations/{id}/transition` — body: `{to_state, actor, note, override_fix?}`
   - `PATCH /entitlements/{id}` — for "fix the entitlement" remediations
   - `DELETE /assignments/{id}` — for "revoke the assignment" remediations
   - `GET /hr/employees/{id}` — lookup
   - `GET /entitlements/{id}` — lookup

3. **Process model** (sketch)
   - Timer every 60s → `GET /violations?state=open` → for each:
     - First, transition to `pending_approval`: `POST /violations/{id}/transition` with `{to_state: "pending_approval", actor: "appian"}`
     - Route by severity:
       - `critical` → compliance review queue (human task)
       - `high` → entitlement-owner queue
       - `medium` / `low` → user-manager queue
     - Human task screen surfaces `evidence` + `suggested_fix` with three buttons:
       - **Approve** → call the appropriate write endpoint (PATCH/DELETE) using `suggested_fix` (or `override_fix` if the human modified it). Then transition to `approved` → `resolved`.
       - **Reject** → transition to `rejected` with a required `note`.
       - **Manual repair** → transition to `manual_repair` and surface in a separate queue for offline handling. When fixed, transition to `resolved`.

## Demo storyline (5 minutes)

See [docs/superpowers/specs/2026-04-27-entitlement-quality-monitor-utility-design.md](docs/superpowers/specs/2026-04-27-entitlement-quality-monitor-utility-design.md) §12.

## Live-demo ops note

The GitHub Actions drift workflow runs every 30 min. During a live demo, **disable the workflow** so the data fabric stays under your control:
```
gh workflow disable simulate-drift
# … run the demo …
gh workflow enable simulate-drift
```
Use `POST /sync/pull-now` if you need to pick up Actions-committed changes during a running session.

## Configuration

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `EQM_BEARER_TOKEN` | yes | — | auth for write + simulate + sync endpoints |
| `EQM_DATA_DIR` | no | `./data` | where JSON files live |
| `EQM_GIT_PUSH_ENABLED` | no | `false` | enable git commit + push from API |
| `EQM_GIT_PUSH_TOKEN` | only if push enabled | — | GitHub PAT for HTTPS push |
| `EQM_GIT_REMOTE_URL` | only if push enabled | — | remote URL incl. token |

## License

Internal demo / prototype. Not for production use.
