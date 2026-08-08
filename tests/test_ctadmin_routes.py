import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from eqm.config import get_settings


def _login(client, *, next_path: str | None = None):
    data = {
        "username": "demo-admin",
        "password": "correct-horse-battery-staple",
    }
    if next_path is not None:
        data["next"] = next_path
    return client.post("/ctadmin/login", data=data, follow_redirects=False)


def test_unauthenticated_ctadmin_pages_redirect_to_login(app_client):
    """Removing the page guard must not expose any of the CTADMIN pages."""
    client, _ = app_client

    for path in [
        "/ctadmin/dashboard",
        "/ctadmin/remediation",
        "/ctadmin/findings/VIO-100",
        "/ctadmin/my-findings",
    ]:
        response = client.get(path, follow_redirects=False)

        assert response.status_code == 303
        parsed = urlparse(response.headers["location"])
        assert parsed.path == "/ctadmin/login"
        assert parse_qs(parsed.query) == {"next": [path]}


def test_login_creates_a_safe_http_only_rotated_session(app_client):
    """Dropping cookie rotation or safe relative redirects would be a session/security bug."""
    client, _ = app_client
    client.cookies.set("ctadmin_session", "pre-login-session", path="/")

    response = _login(client, next_path="/ctadmin/remediation?state=open")

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/remediation?state=open"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "ctadmin_session=pre-login-session" not in cookie


def test_login_rejects_external_and_scheme_relative_next_paths(app_client):
    """Accepting either redirect form would permit credential-phishing redirects."""
    client, _ = app_client

    for next_path in ["https://attacker.example/landing", "//attacker.example/landing"]:
        response = _login(client, next_path=next_path)

        assert response.status_code == 303
        assert response.headers["location"] == "/ctadmin/dashboard"


def test_login_failure_re_renders_the_branded_form_without_a_session(app_client):
    """Changing credential failure into a successful session issuance must be caught."""
    client, _ = app_client

    response = client.post(
        "/ctadmin/login",
        data={"username": "demo-admin", "password": "incorrect"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "Invalid username or password" in response.text
    assert "ctadmin_session" not in response.headers.get("set-cookie", "")


def test_authenticated_placeholder_pages_share_the_ctadmin_shell(app_client):
    """Replacing a protected page with a bare response would lose the shared operator shell."""
    client, _ = app_client
    _login(client)

    for path in [
        "/ctadmin/dashboard",
        "/ctadmin/remediation",
        "/ctadmin/findings/VIO-100",
        "/ctadmin/my-findings",
    ]:
        response = client.get(path)

        assert response.status_code == 200
        assert "Entitlement Quality Monitor" in response.text
        assert "Dashboard" in response.text
        assert "Remediation" in response.text
        assert "My Findings" in response.text
        assert "demo-admin" in response.text


def test_logout_only_accepts_post_and_clears_the_session(app_client):
    """Making logout GET-able or retaining its cookie would weaken session boundaries."""
    client, _ = app_client
    _login(client)

    assert client.get("/ctadmin/logout", follow_redirects=False).status_code == 405
    response = client.post("/ctadmin/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/login"
    assert "ctadmin_session=\"\"" in response.headers["set-cookie"]
    assert client.get("/ctadmin/dashboard", follow_redirects=False).status_code == 303


def test_unauthenticated_ctadmin_data_and_action_paths_return_json_401(app_client):
    """Returning login HTML from programmatic CTADMIN paths breaks JSON clients and CSRF flows."""
    client, _ = app_client

    for method, path in [
        (client.get, "/ctadmin/api/dashboard"),
        (client.post, "/ctadmin/actions/findings/VIO-100/repair"),
    ]:
        response = method(path, follow_redirects=False)

        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"detail": "Authentication required"}


def test_unauthenticated_ctadmin_api_and_action_roots_return_json_401(app_client):
    """Removing no-slash guards would leak FastAPI's 307 normalization redirects."""
    client, _ = app_client

    for method, path in [
        (client.get, "/ctadmin/api"),
        (client.post, "/ctadmin/api"),
        (client.put, "/ctadmin/api"),
        (client.patch, "/ctadmin/api"),
        (client.delete, "/ctadmin/api"),
        (client.get, "/ctadmin/actions"),
        (client.post, "/ctadmin/actions"),
        (client.put, "/ctadmin/actions"),
        (client.patch, "/ctadmin/actions"),
        (client.delete, "/ctadmin/actions"),
    ]:
        response = method(path, follow_redirects=False)

        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"detail": "Authentication required"}


def test_ctadmin_static_assets_do_not_replace_the_existing_static_mount(app_client):
    """A CTADMIN static mount collision would break the established dashboard asset route."""
    client, _ = app_client

    assert client.get("/ctadmin/static/ctadmin.css").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_authenticated_dashboard_renders_the_complete_operator_surface(app_client):
    """Removing an instrument, chart, signal, table, or external asset breaks the page contract."""
    client, _ = app_client
    _login(client)

    response = client.get("/ctadmin/dashboard")

    assert response.status_code == 200
    for hook in [
        "kpi-total", "kpi-critical", "kpi-high", "kpi-not-started", "kpi-in-progress",
        "chart-status", "chart-severity", "chart-target-type", "chart-rule", "chart-coverage",
        "filter-summary", "clear-filters", "findings-results",
    ]:
        assert f'id="{hook}"' in response.text
    assert 'src="/ctadmin/static/charts.js"' in response.text
    assert 'src="/ctadmin/static/dashboard.js"' in response.text
    assert "Appian" not in response.text
    assert "ServiceNow" not in response.text

    embedded = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert embedded is not None
    payload = json.loads(embedded.group(1))
    assert set(payload) == {"kpis", "coverage", "series", "rows", "filters", "pagination"}


def test_authenticated_dashboard_api_returns_the_normalized_json_contract(app_client):
    """Routing the concrete API request to the wildcard or changing its shape breaks all clients."""
    client, _ = app_client
    _login(client)

    response = client.get("/ctadmin/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"kpis", "coverage", "series", "rows", "filters", "pagination"}
    assert set(payload["series"]) == {"status", "severity", "targetType", "rule"}
    assert payload["filters"] == {
        "state": [],
        "severity": [],
        "targetType": [],
        "rule": [],
        "search": "",
        "page": 1,
        "pageSize": 50,
    }


def test_dashboard_api_preserves_repeated_filters_and_normalizes_public_values(app_client):
    """Collapsing repeated values or sending chart buckets directly to the query loses selections."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    (data_dir / "violations.json").write_text(json.dumps([
        {
            "id": "VIO-1", "rule_id": "TOX-01", "rule_name": "Toxic access",
            "severity": "high", "detected_at": "2026-01-01T00:00:00+00:00",
            "target_type": "assignment", "target_id": "ASN-1", "explanation": "Conflict",
            "evidence": {}, "recommended_action": "route_to_compliance", "suggested_fix": {},
            "workflow_state": "pending_approval", "workflow_history": [], "appian_case_id": None,
        }
    ]))
    _login(client)

    response = client.get(
        "/ctadmin/api/dashboard",
        params=[
            ("state", "in_progress"), ("state", "complete"),
            ("severity", "HIGH"), ("targetType", "Assignment"),
            ("rule", "TOX-01"), ("search", " Conflict "),
            ("page", "2"), ("pageSize", "10"),
        ],
    )

    assert response.status_code == 200
    assert response.json()["filters"] == {
        "state": ["in_progress", "complete"],
        "severity": ["high"],
        "targetType": ["assignment"],
        "rule": ["tox-01"],
        "search": "Conflict",
        "page": 2,
        "pageSize": 10,
    }


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("state", "paused"),
        ("severity", "urgent"),
        ("targetType", "database"),
        ("rule", "unknown-rule"),
        ("page", "zero"),
        ("pageSize", "0"),
    ],
)
def test_dashboard_api_rejects_unsupported_filter_values(app_client, parameter, value):
    """Silently accepting an unsupported filter produces an empty, misleading dashboard."""
    client, _ = app_client
    _login(client)

    response = client.get("/ctadmin/api/dashboard", params={parameter: value})

    assert response.status_code == 422
