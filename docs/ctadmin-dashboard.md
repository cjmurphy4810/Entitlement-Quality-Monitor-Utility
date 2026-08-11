# CTADMIN dashboard demo runbook

The CTADMIN Entitlement Quality Monitor is a server-rendered interface over the same deterministic JSON data and rules engine used by the EQMU API. Its four authenticated pages are:

- **Health Dashboard** — portfolio KPIs, entitlement coverage, and filterable status, severity, target-type, and rule charts.
- **Remediation** — filterable findings queue and repair drawer.
- **Finding Detail** — evidence, related records, workflow history, and repair entry point.
- **My Findings** — the same finding analytics scoped to a visibly selected active employee persona.

Confirmed repairs are not UI-only simulations. CTADMIN validates the proposed change against current source data, updates the relevant JSON record, reruns all 13 rules, verifies the original `(rule_id, target_type, target_id)` condition cleared, records the audit history, and persists all affected files as one recoverable operation.

## Configuration

| Environment variable | Required | Default | Description |
|---|---:|---|---|
| `EQM_DATA_DIR` | no | `./data` | Directory containing the five JSON data files. |
| `EQM_BEARER_TOKEN` | yes | none | Token for writes, simulation, and sync API routes; it does not log a user into CTADMIN. |
| `EQM_CTADMIN_USERNAME` | for CTADMIN | none | Username checked by the server-side login route. |
| `EQM_CTADMIN_PASSWORD` | for CTADMIN | none | Password checked by the server. Supply it through environment or platform secrets. |
| `EQM_CTADMIN_SESSION_SECRET` | for CTADMIN | none | HMAC signing secret. It must contain at least 32 non-whitespace characters. |
| `EQM_CTADMIN_SESSION_TTL_SECONDS` | no | `28800` | Session lifetime in seconds; accepted range is 300 through 86400. |
| `EQM_CTADMIN_SECURE_COOKIES` | no | `true` | Adds the cookie `Secure` flag. Set to `0` only for local HTTP. |
| `EQM_CTADMIN_LOGIN_REQUIRED` | no | `true` | Requires a signed CTADMIN login. Set to `false` only for a fully public interactive demo. |
| `EQM_GIT_PUSH_ENABLED` | no | `false` | Enables repository commit/push behavior in API synchronization flows. |
| `EQM_GIT_PUSH_TOKEN` | if push enabled | none | Repository token. Never place it in source or this runbook. |
| `EQM_GIT_REMOTE_URL` | if push enabled | none | Remote used by the synchronization flow. Avoid embedding credentials in checked-in configuration. |

The login creates a signed, HTTP-only, SameSite=Lax session cookie. State-changing CTADMIN actions additionally require the CSRF token bound to that session. Changing the session secret invalidates all existing CTADMIN sessions.

When `EQM_CTADMIN_LOGIN_REQUIRED=false`, anonymous visitors receive the public-demo experience without a login form. This includes the dashboard, JSON data, persona selection, repair previews, and repair confirmations. Anyone with the URL can persist repairs to the demo data while this mode is enabled. The setting does not expose bearer-protected non-CTADMIN API write routes.

Read routes are unauthenticated unless the deployment is protected by an access gateway. Bearer authentication protects writes, simulation, and sync. CTADMIN page/API routes have their separate signed-session protection described above.

## Local demo setup

Install the project once:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

For a live demo, use a disposable copy so repairs do not alter the repository's tracked sample data:

```bash
export EQM_DEMO_DATA_DIR="$(mktemp -d)"
cp data/*.json "$EQM_DEMO_DATA_DIR"/

export EQM_DATA_DIR="$EQM_DEMO_DATA_DIR"
export EQM_BEARER_TOKEN='<set-a-local-api-token>'
export EQM_CTADMIN_USERNAME='demo-admin'
export EQM_CTADMIN_PASSWORD='<set-a-local-demo-password>'
export EQM_CTADMIN_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export EQM_CTADMIN_SESSION_TTL_SECONDS=28800
export EQM_CTADMIN_SECURE_COOKIES=0
export EQM_GIT_PUSH_ENABLED=0

.venv/bin/uvicorn eqm.api:app --port 8080
```

Open `http://127.0.0.1:8080/ctadmin/login` and sign in with the username and password exported above. The original API-support dashboard remains at `http://127.0.0.1:8080/`.

`EQM_CTADMIN_SECURE_COOKIES=0` is intentionally limited to local HTTP. Do not use that setting on a shared host or an HTTPS deployment.

## Demo workflow

1. Sign in at `/ctadmin/login`. Successful authentication redirects to `/ctadmin/dashboard`.
2. On **Health Dashboard**, select a status slice or a severity, target-type, or rule bar. The active segment is highlighted while every segment in that chart remains visible. Add filters from other charts to combine dimensions; use **Clear filters** to return to the full view.
3. Open **My Findings** and choose an employee in the visible **Viewing as** persona control. The signed session remembers this scope. The identity strip, KPIs, charts, and table now describe that employee's direct and assignment-linked findings.
4. Open a finding from **Remediation** or **My Findings**. Review the target record, evidence, recommended action, and workflow history on **Finding Detail**.
5. Choose **Preview repair**. Review any editable proposal or record-selection control. Cancel returns without changing data.
6. Preview again and choose **Confirm repair**. A successful response means the source record was updated, all rules were rerun, and the original rule/target tuple was verified absent from active findings. Dashboard and My Findings totals refresh accordingly.
7. Use **Sign out** before handing the demo to another operator.

Every one of the 13 registered finding types has a repair planner. A stale finding, invalid choice, or repair that does not clear the engine condition is rejected without persisting partial source changes.

## Resetting demo data

Confirmed repairs persist in the directory selected by `EQM_DATA_DIR`. To restore the checked-in sample set in the disposable directory, stop the server, overwrite the five JSON files, and restart it:

```bash
cp data/entitlements.json "$EQM_DEMO_DATA_DIR/entitlements.json"
cp data/hr_employees.json "$EQM_DEMO_DATA_DIR/hr_employees.json"
cp data/cmdb_resources.json "$EQM_DEMO_DATA_DIR/cmdb_resources.json"
cp data/assignments.json "$EQM_DEMO_DATA_DIR/assignments.json"
cp data/violations.json "$EQM_DEMO_DATA_DIR/violations.json"
```

To generate the deterministic small seed instead, stop the server and run:

```bash
EQM_DATA_DIR="$EQM_DEMO_DATA_DIR" \
EQM_BEARER_TOKEN='<set-a-local-api-token>' \
.venv/bin/python -m eqm seed --small
```

The small seed uses the project's fixed seed value. Re-running it restores a reproducible generated dataset, but it is different from copying the checked-in sample files.

## Live-demo stability

The scheduled `simulate-drift` workflow mutates data every 30 minutes. Disable it before a live demo so counts and repair targets do not change while presenting, then enable it afterward:

```bash
gh workflow disable simulate-drift
# Run the demo.
gh workflow enable simulate-drift
```

If synchronization is enabled, avoid triggering a pull or drift tick during the demo. Restart the server after replacing data files so all in-memory file caches begin from the reset dataset.

## Fly.io deployment checklist

Fly.io terminates HTTPS for this app and `fly.toml` forces HTTPS. Keep secure cookies enabled in every Fly deployment:

```bash
fly secrets set \
  EQM_BEARER_TOKEN='<set-the-api-token>' \
  EQM_CTADMIN_USERNAME='<set-the-operator-username>' \
  EQM_CTADMIN_PASSWORD='<set-the-operator-password>' \
  EQM_CTADMIN_SESSION_SECRET='<set-a-random-secret-of-at-least-32-characters>' \
  EQM_CTADMIN_SECURE_COOKIES='1'
```

Generate the session secret outside the repository and pass it directly to the platform secret manager. Do not put credentials in `fly.toml`, shell history, screenshots, test fixtures used outside tests, or commits.

The existing `scripts/deploy.sh` helper does not set CTADMIN secrets. Set all four CTADMIN values shown above before using the dashboard login.

### Toggle hosted-demo login

Turn login off for a public interactive demo:

```bash
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=false --app eqm-utility
```

Restore login protection:

```bash
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=true --app eqm-utility
```

Fly restarts the application after either secret change. Keep the CTADMIN username, password, and session secret configured so protected mode can be restored immediately.

The equivalent Codex chat requests are:

```text
Turn off login for the EQM CTADMIN demo and verify the public dashboard and repair flow.
Turn login back on for the EQM CTADMIN demo and verify anonymous visitors are redirected to login.
```

The container image intentionally omits sample data, and a newly created Fly volume is empty. After the first deploy, initialize the volume before the first CTADMIN visit with the authenticated `POST /simulate/reset` endpoint:

```bash
export EQM_FLY_APP='eqm-utility'
printf 'EQM bearer token: '
IFS= read -r -s EQM_DEPLOY_API_TOKEN
printf '\n'

curl --fail-with-body \
  --request POST \
  --header "Authorization: Bearer ${EQM_DEPLOY_API_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{"small": false}' \
  "https://${EQM_FLY_APP}.fly.dev/simulate/reset"

unset EQM_DEPLOY_API_TOKEN
```

Enter the same bearer-token value stored in the Fly secret when prompted. A successful JSON response reports the generated record counts. This full reset creates all five JSON files in `/data`: entitlements, HR employees, CMDB resources, assignments, and evaluated violations. It is required for a fresh volume; without it, the first CTADMIN page has no data to render.

The Fly volume mounted at `/data` makes initialized data and confirmed repairs persistent across machine restarts. Back up or copy that volume before a demo if you need an exact rollback point.
