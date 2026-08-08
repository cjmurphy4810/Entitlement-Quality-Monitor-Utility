# CTADMIN Entitlement Quality Monitor Utility

A CTADMIN product demo for entitlement governance. It generates and mutates simulated entitlement, HR, CMDB, and assignment records; runs a deterministic rules engine; and presents the resulting findings in a server-rendered operator dashboard with verified remediation.

The rules engine is **strictly deterministic**: no LLM, no fuzzy matching. Every rule is a pure Python function with unit tests. That's the Model Risk Management posture this tool exists to demonstrate.

## What's in here

- **`data/`** — JSON files that ARE the data fabric (entitlements, HR, CMDB, assignments, violations). Version-controlled audit trail.
- **`src/eqm/rules/`** — 13 deterministic rules across four categories.
- **`src/eqm/engine.py`** — runs all rules and reconciles new findings against existing workflow state.
- **`src/eqm/simulator.py`** — drift mode: random, mostly-realistic mutations every 30 min via GitHub Actions.
- **`src/eqm/scenarios.py`** — seven on-cue demo scenarios (e.g. `terminated_user_with_admin`, `sod_payment_breach`).
- **`src/eqm/api.py`** — FastAPI app with read/write/simulate/sync endpoints plus the existing API-support dashboard at `/`.
- **`src/eqm/ctadmin/`** — authenticated CTADMIN Health Dashboard, Remediation, Finding Detail, and My Findings pages at `/ctadmin/*`.
- **`fly.toml`, `Dockerfile`, `scripts/deploy.sh`** — Fly.io deployment.

## Quickstart (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export EQM_BEARER_TOKEN=demo-token
export EQM_DATA_DIR=./data
export EQM_CTADMIN_USERNAME=demo-admin
export EQM_CTADMIN_PASSWORD='<set-a-local-demo-password>'
export EQM_CTADMIN_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export EQM_CTADMIN_SECURE_COOKIES=0

python -m eqm seed --small
python -m eqm drift
python -m eqm scenario kitchen_sink

uvicorn eqm.api:app --reload --port 8080
# API-support dashboard: http://localhost:8080/
# CTADMIN login: http://localhost:8080/ctadmin/login
```

Use the password assigned to `EQM_CTADMIN_PASSWORD` to sign in. Local plain HTTP requires `EQM_CTADMIN_SECURE_COOKIES=0`; hosted HTTPS must use secure cookies. Confirmed repairs update JSON records under `EQM_DATA_DIR` and rerun the rules engine before the finding is resolved.

See [docs/ctadmin-dashboard.md](docs/ctadmin-dashboard.md) for the full configuration reference, disposable-data demo workflow, reset procedure, and Fly.io checklist.

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

## API integration

The existing API remains available for record generation and automation. Read routes are unauthenticated unless the deployment is protected by an access gateway. Bearer authentication protects writes, simulation, and sync; examples include `POST /violations/{id}/transition`, `PATCH /entitlements/{id}`, `DELETE /assignments/{id}`, and the simulation routes. The additional CTADMIN dashboard is a direct product interface over the same data and does not require an external workflow platform.

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
| `EQM_CTADMIN_USERNAME` | CTADMIN UI | — | server-side login username |
| `EQM_CTADMIN_PASSWORD` | CTADMIN UI | — | server-side login password; provide as a secret |
| `EQM_CTADMIN_SESSION_SECRET` | CTADMIN UI | — | signing secret, at least 32 characters |
| `EQM_CTADMIN_SESSION_TTL_SECONDS` | no | `28800` | signed-session lifetime, 300–86400 seconds |
| `EQM_CTADMIN_SECURE_COOKIES` | no | `true` | require HTTPS when sending the session cookie |

## License

Internal demo / prototype. Not for production use.
