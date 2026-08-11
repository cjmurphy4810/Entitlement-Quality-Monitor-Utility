# CTADMIN Login Toggle Design

**Date:** 2026-08-11

## Goal

Allow the hosted CTADMIN demo at `/ctadmin/*` to run either as an authenticated operator surface or as a fully public interactive demo, including repair actions, without requiring code edits between modes.

## Configuration

Add `EQM_CTADMIN_LOGIN_REQUIRED`, parsed as a boolean and defaulting to `true`. The secure default preserves the existing deployment behavior. Setting it to `false` enables public-demo mode.

Changing the Fly.io environment value and restarting/redeploying the application changes the mode. Existing CTADMIN credentials and the session secret remain configured so login can be restored immediately.

## Request Behavior

When login is required, page, JSON, logout, persona, preview, and repair routes keep their existing signed-session and CSRF behavior.

When login is not required, requests without a valid session receive an application-created public-demo principal. This principal uses the operator persona (`ctadmin`) and supplies the template/API context needed by the existing dashboard, filters, persona selector, previews, and repairs. A valid signed session, if present, may continue to supply its selected persona.

The public principal's CSRF token is derived server-side from the configured session secret and a fixed public-demo purpose string. Existing mutation endpoints continue requiring the CSRF token submitted by the rendered application. This retains protection against blind cross-origin browser form submissions, but it is not an authorization boundary: public-mode users can intentionally retrieve the application and invoke repairs.

The login page redirects to the dashboard in public mode. The shared header identifies the session as `Public demo` and omits the logout form when there is no signed user session.

## Security and Data Consequences

Public mode intentionally permits anyone with the URL to view data, select personas, preview repairs, and persist repairs to the Fly volume. The runbook must state this plainly. Login-required mode remains the default and restores the existing access boundary.

No bearer-protected non-CTADMIN API write route becomes public. The toggle applies only to the CTADMIN surface.

## Tests

Route tests will prove that:

- The default setting still redirects anonymous page requests and rejects anonymous JSON/action requests.
- Public mode renders the dashboard and serves dashboard JSON without a session.
- Public mode can preview and execute a repair using the rendered CSRF token.
- Public mode identifies itself in the shell and omits logout.
- The login page redirects to the dashboard in public mode.

Existing CTADMIN and API regression tests must remain green.

## Operations

The runbook will document:

```bash
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=false --app eqm-utility
fly secrets set EQM_CTADMIN_LOGIN_REQUIRED=true --app eqm-utility
```

Equivalent Codex requests are:

- `Turn off login for the EQM CTADMIN demo and verify the public dashboard and repair flow.`
- `Turn login back on for the EQM CTADMIN demo and verify anonymous visitors are redirected to login.`
