# CTADMIN Login Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure-by-default environment toggle that can expose the full CTADMIN demo, including repair actions, without login.

**Architecture:** `Settings` owns the boolean deployment switch. The CTADMIN route guard returns either the existing signed-session principal or a server-created public-demo principal; all existing pages, JSON endpoints, and mutation paths continue consuming the same `SessionPrincipal` interface. The template uses an explicit public-mode value to replace logout with a public-demo identity.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, Jinja2, pytest, Fly.io.

## Global Constraints

- `EQM_CTADMIN_LOGIN_REQUIRED` defaults to `true`.
- The toggle applies only to `/ctadmin/*`; bearer-protected API writes remain unchanged.
- Public mode includes repair actions and therefore permits persistent demo-data changes.
- Authenticated mode retains the current signed-session and CSRF behavior.
- Preserve unrelated worktree changes, including the existing edit to `src/eqm/api.py`.

---

### Task 1: Public-demo principal and route behavior

**Files:**
- Modify: `src/eqm/config.py`
- Modify: `src/eqm/ctadmin/routes.py`
- Modify: `src/eqm/ctadmin/templates/base.html`
- Modify: `tests/test_ctadmin_routes.py`

**Interfaces:**
- Consumes: `Settings`, `SessionPrincipal`, `get_principal(request, settings)`, and existing route helpers.
- Produces: `Settings.ctadmin_login_required: bool`, public-aware `_page_principal(...)` and `_api_principal(...)`, plus `public_demo: bool` template context.

- [ ] **Step 1: Write failing public-mode route tests**

Add tests that clone the fixture settings with `ctadmin_login_required=False`, clear the settings cache, and prove an anonymous client can render `/ctadmin/dashboard`, call `/ctadmin/api/dashboard`, see `Public demo`, and does not see `action="/ctadmin/logout"`.

```python
def test_public_demo_mode_serves_dashboard_without_session(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setenv("EQM_CTADMIN_LOGIN_REQUIRED", "false")
    get_settings.cache_clear()

    page = client.get("/ctadmin/dashboard", follow_redirects=False)
    api = client.get("/ctadmin/api/dashboard")

    assert page.status_code == 200
    assert api.status_code == 200
    assert "Public demo" in page.text
    assert 'action="/ctadmin/logout"' not in page.text
```

Add a login test asserting `GET /ctadmin/login` returns `303` to `/ctadmin/dashboard` in public mode. Add a mutation test that extracts the rendered hidden CSRF token, previews an existing repairable finding, and posts its existing valid repair payload successfully without a session.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py -k 'public_demo' -q`

Expected: FAIL because `EQM_CTADMIN_LOGIN_REQUIRED` has no behavioral effect and anonymous routes redirect or return 401.

- [ ] **Step 3: Add the setting and public principal**

Add to `Settings`:

```python
ctadmin_login_required: bool = True
```

In `routes.py`, derive a stable CSRF value using HMAC-SHA256 over the configured session secret and the byte string `b"ctadmin-public-demo-csrf-v1"`, URL-safe encode it, and create:

```python
def _public_demo_principal(settings: Settings) -> SessionPrincipal:
    return SessionPrincipal(
        username="Public demo",
        csrf_token=derived_token,
        persona_id="ctadmin",
        nonce="public-demo",
    )
```

Update both principal helpers to use an existing valid signed session when available, otherwise return the public principal when `ctadmin_login_required` is false, and otherwise preserve the current redirect/401 behavior. Redirect `GET /login` to `/ctadmin/dashboard` in public mode. Add `public_demo=not settings.ctadmin_login_required` to template context and conditionally render either `Public demo` or the existing username/logout form.

- [ ] **Step 4: Run route and auth tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_ctadmin_routes.py tests/test_ctadmin_auth.py tests/test_e2e.py -q`

Expected: PASS.

- [ ] **Step 5: Run lint**

Run: `.venv/bin/ruff check src/eqm/config.py src/eqm/ctadmin/routes.py tests/test_ctadmin_routes.py`

Expected: PASS with no findings.

- [ ] **Step 6: Commit application behavior**

```bash
git add src/eqm/config.py src/eqm/ctadmin/routes.py src/eqm/ctadmin/templates/base.html tests/test_ctadmin_routes.py
git commit -m "feat(ctadmin): add reversible login toggle"
```

---

### Task 2: Operations documentation and deployment verification

**Files:**
- Modify: `README.md`
- Modify: `docs/ctadmin-dashboard.md`

**Interfaces:**
- Consumes: `EQM_CTADMIN_LOGIN_REQUIRED` from Task 1.
- Produces: exact local/Fly toggle instructions and reusable Codex request wording.

- [ ] **Step 1: Document the setting and its risk**

Add the variable to both configuration tables, state that it defaults to `true`, and document:

```bash
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=false --app eqm-utility
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=true --app eqm-utility
```

State explicitly that public mode allows any visitor to execute persistent repairs. Include these chat requests:

```text
Turn off login for the EQM CTADMIN demo and verify the public dashboard and repair flow.
Turn login back on for the EQM CTADMIN demo and verify anonymous visitors are redirected to login.
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md docs/ctadmin-dashboard.md
git commit -m "docs(ctadmin): document login toggle operations"
```

- [ ] **Step 4: Deploy code and enable public mode**

Run: `fly deploy --app eqm-utility`, then `fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=false --app eqm-utility`.

Expected: Fly reports a healthy release and restarts the machine with the new setting.

- [ ] **Step 5: Verify the live anonymous flow**

Open `https://eqm-utility.fly.dev/ctadmin/dashboard` in a clean browser context. Confirm HTTP 200 without a login redirect, `Public demo` in the header, dashboard data and charts load, a repair preview opens, and one valid repair completes. Confirm `/ctadmin/login` redirects to the dashboard.

- [ ] **Step 6: Record deployment state**

Run: `fly status --app eqm-utility` and `fly releases --app eqm-utility`.

Expected: the latest release is healthy and public mode remains enabled.
