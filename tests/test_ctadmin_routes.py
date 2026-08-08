import asyncio
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from eqm.config import get_settings
from eqm.ctadmin.auth import SessionCodec
from eqm.ctadmin.repairs import RepairValidationError
from eqm.ctadmin.routes import _finding_context
from eqm.ctadmin.service import RepairDidNotClearError, StaleFindingError
from eqm.models import Violation
from eqm.persistence import JsonStore


def _login(client, *, next_path: str | None = None):
    data = {
        "username": "demo-admin",
        "password": "correct-horse-battery-staple",
    }
    if next_path is not None:
        data["next"] = next_path
    return client.post("/ctadmin/login", data=data, follow_redirects=False)


def _csrf(client) -> str:
    settings = get_settings()
    token = client.cookies.get("ctadmin_session")
    assert token is not None
    return (
        SessionCodec(
            settings.ctadmin_session_secret.get_secret_value(),
            settings.ctadmin_session_ttl_seconds,
        )
        .decode(token)
        .csrf_token
    )


def _finding_record(**changes):
    record = {
        "id": "VIO-100",
        "rule_id": "ENT-Q-01",
        "rule_name": "PBL completeness",
        "severity": "high",
        "detected_at": "2026-08-07T12:00:00+00:00",
        "target_type": "entitlement",
        "target_id": "ENT-1",
        "explanation": "Description is too short <unsafe>.",
        "evidence": {"pbl_description": "bad", "reasons": ["length=3 < 20"]},
        "recommended_action": "update_entitlement_field",
        "suggested_fix": {"pbl_description": "Describe the approved business use."},
        "workflow_state": "open",
        "workflow_history": [
            {
                "from_state": "open",
                "to_state": "pending_approval",
                "actor": "reviewer",
                "timestamp": "2026-08-07T12:30:00+00:00",
                "note": "Owner review <required>",
                "override_fix": None,
            }
        ],
        "appian_case_id": None,
    }
    record.update(changes)
    return record


def _seed_route_data(data_dir):
    (data_dir / "entitlements.json").write_text(
        json.dumps(
            [
                {
                    "id": "ENT-1",
                    "name": "Ledger Reader",
                    "pbl_description": "bad",
                    "access_tier": 4,
                    "acceptable_roles": ["operations"],
                    "division": "tech_ops",
                    "linked_resource_ids": ["RES-1"],
                    "sod_tags": [],
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        )
    )
    (data_dir / "hr_employees.json").write_text(
        json.dumps(
            [
                {
                    "id": "EMP-1",
                    "full_name": "Casey Example",
                    "email": "casey@example.com",
                    "current_role": "operations",
                    "current_division": "tech_ops",
                    "status": "active",
                    "role_history": [],
                    "manager_id": None,
                    "hired_at": "2025-01-01T00:00:00+00:00",
                    "terminated_at": None,
                }
            ]
        )
    )
    (data_dir / "cmdb_resources.json").write_text(
        json.dumps(
            [
                {
                    "id": "RES-1",
                    "name": "Ledger API",
                    "type": "api",
                    "criticality": "low",
                    "owner_division": "tech_ops",
                    "environment": "prod",
                    "linked_entitlement_ids": ["ENT-1"],
                    "description": "Ledger API",
                }
            ]
        )
    )
    (data_dir / "assignments.json").write_text(
        json.dumps(
            [
                {
                    "id": "ASN-1",
                    "employee_id": "EMP-1",
                    "entitlement_id": "ENT-1",
                    "granted_at": "2026-01-01T00:00:00+00:00",
                    "granted_by": "system",
                    "last_certified_at": None,
                    "active": True,
                }
            ]
        )
    )
    records = [
        _finding_record(detected_at="2026-08-07T14:00:00+00:00"),
        _finding_record(
            id="VIO-101",
            rule_id="HR-01",
            rule_name="Role mismatch",
            severity="medium",
            target_type="assignment",
            target_id="ASN-1",
            workflow_state="pending_approval",
            explanation="Employee role does not match entitlement.",
            evidence={},
            workflow_history=[],
            recommended_action="auto_revoke_assignment",
            suggested_fix={},
            detected_at="2026-08-07T13:00:00+00:00",
        ),
        _finding_record(
            id="VIO-102",
            target_id="ENT-2",
            workflow_state="resolved",
            severity="low",
            explanation="Resolved description issue.",
            workflow_history=[],
        ),
    ]
    (data_dir / "violations.json").write_text(json.dumps(records))
    return records


def _seed_persona_route_data(data_dir):
    """Seed two visible personas plus active and terminal findings for exact scoping."""
    records = _seed_route_data(data_dir)
    employees = json.loads((data_dir / "hr_employees.json").read_text())
    employees.append(
        {
            "id": "EMP-2",
            "full_name": "Jordan Other",
            "email": "jordan@example.com",
            "current_role": "developer",
            "current_division": "tech_dev",
            "status": "active",
            "role_history": [],
            "manager_id": None,
            "hired_at": "2025-01-01T00:00:00+00:00",
            "terminated_at": None,
        }
    )
    (data_dir / "hr_employees.json").write_text(json.dumps(employees))
    entitlements = json.loads((data_dir / "entitlements.json").read_text())
    entitlements.append(
        {
            "id": "ENT-2",
            "name": "Build Console",
            "pbl_description": "Build console access for approved development work.",
            "access_tier": 3,
            "acceptable_roles": ["developer"],
            "division": "tech_dev",
            "linked_resource_ids": [],
            "sod_tags": [],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    (data_dir / "entitlements.json").write_text(json.dumps(entitlements))
    assignments = json.loads((data_dir / "assignments.json").read_text())
    assignments.append(
        {
            "id": "ASN-2",
            "employee_id": "EMP-2",
            "entitlement_id": "ENT-2",
            "granted_at": "2026-01-01T00:00:00+00:00",
            "granted_by": "system",
            "last_certified_at": None,
            "active": True,
        }
    )
    (data_dir / "assignments.json").write_text(json.dumps(assignments))
    records.extend(
        [
            _finding_record(
                id="VIO-103",
                rule_id="TOX-01",
                rule_name="Maker-checker conflict",
                severity="high",
                target_type="employee",
                target_id="EMP-1",
                workflow_state="resolved",
                explanation="Casey's conflict was resolved.",
                evidence={},
                workflow_history=[],
                recommended_action="route_to_compliance",
                suggested_fix={},
            ),
            _finding_record(
                id="VIO-200",
                rule_id="HR-01",
                rule_name="Role mismatch",
                severity="critical",
                target_type="assignment",
                target_id="ASN-2",
                workflow_state="open",
                explanation="Jordan's assignment is outside Casey's scope.",
                evidence={},
                workflow_history=[],
                recommended_action="auto_revoke_assignment",
                suggested_fix={},
            ),
        ]
    )
    (data_dir / "violations.json").write_text(json.dumps(records))
    return records


@pytest.mark.asyncio
async def test_finding_context_cannot_mix_interleaved_files(tmp_path, monkeypatch):
    _seed_route_data(tmp_path)
    context_store = JsonStore(tmp_path)
    writer = JsonStore(tmp_path)
    entitlements = await writer.read("entitlements.json")
    entitlements[0]["name"] = "Changed Mid-context"
    actual_read = context_store.read
    first_file_read = asyncio.Event()
    release_context = asyncio.Event()

    async def pause_after_violations(name):
        data = await actual_read(name)
        if name == "violations.json":
            first_file_read.set()
            await release_context.wait()
        return data

    monkeypatch.setattr(context_store, "read", pause_after_violations)
    context_task = asyncio.create_task(
        _finding_context(context_store, "VIO-100")
    )
    await first_file_read.wait()
    writer_task = asyncio.create_task(writer.write("entitlements.json", entitlements))
    await asyncio.sleep(0)
    writer_waited = not writer_task.done()

    release_context.set()
    context = await context_task
    await writer_task

    assert writer_waited
    assert context is not None
    assert context["target"]["name"] == "Ledger Reader"


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


@pytest.mark.parametrize(
    "next_path",
    [
        "/ctadmin/../outside",
        "/ctadmin/%2e%2e/outside",
        "/ctadmin/%252e%252e/outside",
        "/ctadmin/..%2foutside",
        "/ctadmin/%2e%2e%5coutside",
        "/ctadmin/folder%5c..%5c..%5coutside",
    ],
)
def test_login_rejects_dot_segment_and_backslash_ctadmin_next_paths(app_client, next_path):
    """A CTADMIN-looking path must not escape its prefix after browser/server decoding."""
    client, _ = app_client

    response = _login(client, next_path=next_path)

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/dashboard"


def test_login_preserves_a_legitimate_ctadmin_finding_next_path_and_query(app_client):
    client, _ = app_client
    next_path = "/ctadmin/findings/VIO-100?origin=%2Fctadmin%2Fmy-findings%3Fseverity%3Dhigh"

    response = _login(client, next_path=next_path)

    assert response.status_code == 303
    assert response.headers["location"] == next_path


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
    _seed_route_data(get_settings().data_dir)
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


def test_logout_requires_signed_session_and_csrf_then_clears_the_session(app_client):
    """Logout is a state-changing session action and must carry both protections."""
    client, _ = app_client

    assert client.get("/ctadmin/logout", follow_redirects=False).status_code == 405
    assert client.post("/ctadmin/logout", follow_redirects=False).status_code == 401
    _login(client)
    assert client.post("/ctadmin/logout", follow_redirects=False).status_code == 403
    dashboard = client.get("/ctadmin/dashboard")
    assert 'action="/ctadmin/logout"' in dashboard.text
    assert f'name="csrf_token" value="{_csrf(client)}"' in dashboard.text

    response = client.post(
        "/ctadmin/logout",
        data={"csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/login"
    assert 'ctadmin_session=""' in response.headers["set-cookie"]
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
        "kpi-total-assignments",
        "kpi-total-findings",
        "kpi-open",
        "kpi-high-critical",
        "kpi-catalog-findings",
        "chart-status",
        "chart-severity",
        "chart-target-type",
        "chart-rule",
        "chart-coverage",
        "filter-summary",
        "clear-filters",
        "findings-results",
    ]:
        assert f'id="{hook}"' in response.text
    assert 'src="/ctadmin/static/charts.js"' in response.text
    assert 'src="/ctadmin/static/dashboard.js"' in response.text
    assert ">Clear Filters</button>" in response.text
    assert "Appian" not in response.text
    assert "ServiceNow" not in response.text
    headings = re.findall(r"<th[^>]*>([^<]+)</th>", response.text)
    assert headings == [
        "Violation",
        "User",
        "Rule",
        "Status",
        "Severity",
        "Target",
        "Recommended Action",
        "Action",
    ]

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
    assert set(payload["series"]) == {
        "assignmentStatus",
        "status",
        "severity",
        "targetType",
        "rule",
    }
    assert payload["filters"] == {
        "state": [],
        "severity": [],
        "targetType": [],
        "rule": [],
        "assignmentStatus": [],
        "coverage": [],
        "search": "",
        "page": 1,
        "pageSize": 50,
    }


def test_dashboard_api_preserves_repeated_filters_and_normalizes_public_values(app_client):
    """Collapsing repeated values or sending chart buckets directly to the query loses selections."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    (data_dir / "violations.json").write_text(
        json.dumps(
            [
                {
                    "id": "VIO-1",
                    "rule_id": "TOX-01",
                    "rule_name": "Toxic access",
                    "severity": "high",
                    "detected_at": "2026-01-01T00:00:00+00:00",
                    "target_type": "assignment",
                    "target_id": "ASN-1",
                    "explanation": "Conflict",
                    "evidence": {},
                    "recommended_action": "route_to_compliance",
                    "suggested_fix": {},
                    "workflow_state": "pending_approval",
                    "workflow_history": [],
                    "appian_case_id": None,
                }
            ]
        )
    )
    _login(client)

    response = client.get(
        "/ctadmin/api/dashboard",
        params=[
            ("state", "in_progress"),
            ("state", "complete"),
            ("severity", "HIGH"),
            ("targetType", "Assignment"),
            ("rule", "TOX-01"),
            ("search", " Conflict "),
            ("page", "2"),
            ("pageSize", "10"),
        ],
    )

    assert response.status_code == 200
    assert response.json()["filters"] == {
        "state": ["in_progress", "complete"],
        "severity": ["high"],
        "targetType": ["assignment"],
        "rule": ["tox-01"],
        "assignmentStatus": [],
        "coverage": [],
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
        ("assignmentStatus", "unknown-status"),
        ("coverage", "unknown-coverage"),
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


def test_remediation_renders_all_workflow_kpis_filters_columns_and_pagination(app_client):
    """The administrative queue must include terminal work and preserve its operator context."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    response = client.get("/ctadmin/remediation", params={"pageSize": "2"})

    assert response.status_code == 200
    for expected in [
        "Not started",
        "In progress",
        "Complete",
        ">1<",
        "state-filter",
        "severity-filter",
        "rule-filter",
        "target-filter",
        "remediation-search",
        "Page 1 of 2",
        "Violation",
        "User",
        "Rule",
        "Status",
        "Severity",
        "Target",
        "Recommended action",
        "VIO-100",
        "VIO-101",
        "Repair",
    ]:
        assert expected in response.text
    assert "VIO-102" not in response.text
    assert "/ctadmin/findings/VIO-100?origin=" in response.text


def test_remediation_applies_all_supported_filters(app_client):
    """Ignoring one queue control would misrepresent the operator's active scope."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    response = client.get(
        "/ctadmin/remediation",
        params={
            "state": "in_progress",
            "severity": "medium",
            "rule": "HR-01",
            "targetType": "assignment",
            "search": "Role mismatch",
        },
    )

    assert response.status_code == 200
    assert "VIO-101" in response.text
    assert "VIO-100" not in response.text
    assert 'value="in_progress" selected' in response.text
    assert 'value="medium" selected' in response.text
    assert 'value="assignment" selected' in response.text


def test_finding_detail_renders_safe_internal_evidence_context_and_history(app_client):
    """Dropping internal evidence, context, or audit history makes a repair unverifiable."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    response = client.get(
        "/ctadmin/findings/VIO-100",
        params={"origin": "/ctadmin/remediation?state=not_started"},
    )

    assert response.status_code == 200
    for expected in [
        "VIO-100",
        "ENT-Q-01",
        "PBL completeness",
        "High",
        "Open",
        "ENT-1",
        "Ledger Reader",
        "Casey Example",
        "Structured evidence",
        "pbl_description",
        "Suggested fix",
        "Workflow history",
        "reviewer",
        "Owner review",
        "Preview repair",
        "Back to remediation",
    ]:
        assert expected in response.text
    assert "<unsafe>" not in response.text
    assert "&lt;unsafe&gt;" in response.text
    assert "%2Fctadmin%2Fremediation%3Fstate%3Dnot_started" not in response.text


def test_finding_detail_returns_404_for_missing_record(app_client):
    client, _ = app_client
    _login(client)

    response = client.get("/ctadmin/findings/VIO-MISSING")

    assert response.status_code == 404
    assert response.json() == {"detail": "Finding not found"}


@pytest.mark.parametrize(
    ("rule_id", "changes", "kind"),
    [
        ("ENT-Q-01", {}, "pbl_textarea"),
        ("ENT-Q-02", {}, "pbl_textarea"),
        ("ENT-Q-03", {}, "direct_change"),
        ("ENT-Q-04", {}, "direct_change"),
        ("HR-03", {"target_type": "assignment", "target_id": "ASN-1"}, "acknowledgement"),
        ("CMDB-01", {}, "resource_select"),
        ("CMDB-02", {}, "direct_change"),
        ("TOX-01", {"target_type": "employee", "target_id": "EMP-1"}, "binary_side"),
        ("TOX-02", {"target_type": "employee", "target_id": "EMP-1"}, "binary_side"),
        ("TOX-03", {"target_type": "employee", "target_id": "EMP-1"}, "assignment_multiselect"),
        ("HR-01", {"target_type": "assignment", "target_id": "ASN-1"}, "direct_change"),
        ("HR-02", {"target_type": "assignment", "target_id": "ASN-1"}, "direct_change"),
        ("HR-04", {"target_type": "assignment", "target_id": "ASN-1"}, "direct_change"),
    ],
)
def test_repair_preview_returns_rule_specific_safe_schema(app_client, rule_id, changes, kind):
    """Collapsing rule families into one ambiguous form can submit the wrong repair shape."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_route_data(data_dir)
    record = _finding_record(rule_id=rule_id, rule_name=f"{rule_id} finding", **changes)
    (data_dir / "violations.json").write_text(json.dumps([record]))
    _login(client)

    response = client.get("/ctadmin/api/findings/VIO-100/repair-preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["violationId"] == "VIO-100"
    assert payload["ruleId"] == rule_id
    assert payload["kind"] == kind
    assert isinstance(payload["evidence"], dict)
    assert isinstance(payload["fields"], list)
    assert payload["confirmLabel"] == "Confirm repair"


def test_repair_preview_and_action_have_concrete_slash_routes_and_method_guards(app_client):
    """Wildcard shadowing or slash normalization must not bypass concrete route semantics."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    for path in [
        "/ctadmin/api/findings/VIO-100/repair-preview",
        "/ctadmin/api/findings/VIO-100/repair-preview/",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
    for path in [
        "/ctadmin/actions/findings/VIO-100/repair",
        "/ctadmin/actions/findings/VIO-100/repair/",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404
        assert response.headers.get("location") is None


@pytest.mark.parametrize("suffix", ["", "/"])
def test_repair_action_rejects_missing_csrf_without_mutating_data(app_client, suffix):
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_route_data(data_dir)
    before = {path.name: path.read_bytes() for path in data_dir.glob("*.json")}
    _login(client)

    response = client.post(
        f"/ctadmin/actions/findings/VIO-100/repair{suffix}",
        json={"pbl_description": "Provides read-only access for approved ledger operations."},
    )

    assert response.status_code == 403
    assert {path.name: path.read_bytes() for path in data_dir.glob("*.json")} == before


def test_repair_action_returns_a_verified_receipt(app_client):
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={"pbl_description": "Provides read-only access for approved ledger operations."},
        headers={"X-CSRF-Token": _csrf(client)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleared"] is True
    assert payload["violationId"] == "VIO-100"
    assert payload["workflowState"] == "resolved"
    assert payload["recordIds"] == ["ENT-1"]
    assert payload["changes"][0]["after"]["pbl_description"].startswith("Provides read-only")
    assert payload["changes"][0]["before"] == {"pbl_description": "bad"}
    assert payload["evaluation"] == {"cleared": True, "workflowState": "resolved"}

    detail = client.get("/ctadmin/findings/VIO-100")
    assert "Repair receipt" in detail.text
    assert "ENT-1" in detail.text
    assert "pbl description" in detail.text.lower()
    assert "Provides read-only access" in detail.text
    assert "Cleared" in detail.text


def test_repair_confirmation_is_throttled_before_execution(app_client, monkeypatch):
    """The over-budget confirm request returns 429 and never reaches repair evaluation."""
    from eqm.ctadmin.auth import MutationThrottle

    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)
    calls = 0

    async def invalid(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RepairValidationError("invalid")

    monkeypatch.setattr("eqm.ctadmin.routes.execute_repair", invalid)
    monkeypatch.setattr(
        "eqm.ctadmin.routes.mutation_throttle",
        MutationThrottle(limit=2, window_seconds=60, max_keys=10),
    )
    headers = {"X-CSRF-Token": _csrf(client)}
    assert client.post("/ctadmin/actions/findings/VIO-100/repair", json={}, headers=headers).status_code == 422
    assert client.post("/ctadmin/actions/findings/VIO-100/repair", json={}, headers=headers).status_code == 422

    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={},
        headers=headers,
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many mutation attempts"}
    assert calls == 2


def test_authenticated_ctadmin_responses_disable_browser_storage(app_client):
    """Protected pages, JSON, redirects, and action responses may not be browser-cached."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    responses = [
        client.get("/ctadmin/dashboard"),
        client.get("/ctadmin/api/dashboard"),
        client.get("/ctadmin/api/findings/VIO-100/repair-preview"),
        client.post(
            "/ctadmin/actions/persona",
            data={"csrf_token": _csrf(client), "persona_id": "EMP-1"},
            follow_redirects=False,
        ),
    ]
    assert all(response.headers.get("cache-control") == "no-store" for response in responses)
    assert "cache-control" not in client.get("/ctadmin/login").headers
    assert "no-store" not in client.get("/ctadmin/static/dashboard.js").headers.get(
        "cache-control", ""
    )


def test_repair_action_translates_typed_conflicts_and_validation(app_client, monkeypatch):
    """Typed repair failures let the drawer preserve input and direct the operator accurately."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 422
    assert response.json()["type"] == "validation_error"

    async def stale(*_args, **_kwargs):
        raise StaleFindingError("Finding changed")

    monkeypatch.setattr("eqm.ctadmin.routes.execute_repair", stale)
    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 409
    assert response.json() == {"type": "stale_finding", "detail": "Finding changed"}

    async def nonclearing(*_args, **_kwargs):
        raise RepairDidNotClearError(Violation(**_finding_record()))

    monkeypatch.setattr("eqm.ctadmin.routes.execute_repair", nonclearing)
    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 409
    assert response.json()["type"] == "repair_did_not_clear"
    assert response.json()["remaining"]["reason"] == "Description is too short <unsafe>."


def test_terminal_finding_has_history_but_no_repair_trigger(app_client):
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_route_data(data_dir)
    (data_dir / "violations.json").write_text(
        json.dumps([_finding_record(workflow_state="resolved")])
    )
    _login(client)

    response = client.get("/ctadmin/findings/VIO-100")

    assert response.status_code == 200
    assert "Finding resolved" in response.text
    assert "Preview repair" not in response.text

    preview = client.get("/ctadmin/api/findings/VIO-100/repair-preview")
    assert preview.status_code == 409


def test_repair_action_hides_unexpected_server_details(app_client, monkeypatch, caplog):
    """An internal repair exception must be logged without exposing its detail to the client."""
    client, _ = app_client
    _seed_route_data(get_settings().data_dir)
    _login(client)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("secret filesystem detail")

    monkeypatch.setattr("eqm.ctadmin.routes.execute_repair", fail)
    response = client.post(
        "/ctadmin/actions/findings/VIO-100/repair",
        json={},
        headers={"X-CSRF-Token": _csrf(client)},
    )

    assert response.status_code == 500
    assert response.json() == {
        "type": "server_error",
        "detail": "The repair could not be completed.",
    }
    assert "secret filesystem detail" not in response.text
    assert "secret filesystem detail" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "correlation_id=" in caplog.text


def test_my_findings_without_a_persona_prompts_with_visible_searchable_options(app_client):
    """The demo perspective control must remain visible even before a persona is chosen."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)

    response = client.get("/ctadmin/my-findings")

    assert response.status_code == 200
    for expected in [
        "Choose an employee perspective",
        "Demo perspective",
        "persona-selector",
        "persona-search",
        "Casey Example",
        "Jordan Other",
        "EMP-1",
        "EMP-2",
    ]:
        assert expected in response.text
    assert 'id="dashboard-data"' not in response.text
    api_response = client.get("/ctadmin/api/my-findings")
    assert api_response.status_code == 409
    assert api_response.json() == {"detail": "Select a current active employee persona"}


def test_persona_action_validates_csrf_route_shape_and_current_hr_data(app_client):
    """Persona changes are authenticated mutations and may select only current active HR rows."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)

    for suffix in ["", "/"]:
        unauthenticated = client.post(
            f"/ctadmin/actions/persona{suffix}",
            data={"persona_id": "EMP-1", "csrf_token": "missing"},
            follow_redirects=False,
        )
        assert unauthenticated.status_code == 401

    _login(client)
    for suffix in ["", "/"]:
        missing_csrf = client.post(
            f"/ctadmin/actions/persona{suffix}",
            data={"persona_id": "EMP-1"},
            follow_redirects=False,
        )
        assert missing_csrf.status_code == 403
        assert client.get(f"/ctadmin/actions/persona{suffix}").status_code == 404

    invalid = client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-MISSING", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "Select a current active employee persona"}


def test_persona_selection_persists_signed_identity_scope_and_original_expiry(app_client):
    """Changing perspective must retain the authenticated session's security identity and lifetime."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)
    settings = get_settings()
    codec = SessionCodec(
        settings.ctadmin_session_secret.get_secret_value(),
        settings.ctadmin_session_ttl_seconds,
    )
    before = codec.decode(client.cookies.get("ctadmin_session"))

    response = client.post(
        "/ctadmin/actions/persona/",
        data={
            "persona_id": "EMP-1",
            "csrf_token": before.csrf_token,
            "return_to": "/ctadmin/my-findings?severity=high",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/my-findings?severity=high"
    after = codec.decode(client.cookies.get("ctadmin_session"))
    assert after.username == before.username
    assert after.csrf_token == before.csrf_token
    assert after.nonce == before.nonce
    assert after.persona_id == "EMP-1"
    assert after.expires_at == before.expires_at

    page = client.get("/ctadmin/my-findings")
    assert "Casey Example" in page.text
    assert "EMP-1" in page.text
    assert "Persona: EMP-1" in client.get("/ctadmin/dashboard").text


def test_persona_action_accepts_deliberate_clear_and_rejects_external_return(app_client):
    """An empty submitted persona clears perspective without permitting an open redirect."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)
    selected = client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert selected.status_code == 303

    cleared = client.post(
        "/ctadmin/actions/persona",
        data={
            "persona_id": "",
            "csrf_token": _csrf(client),
            "return_to": "https://attacker.example/persona",
        },
        follow_redirects=False,
    )

    assert cleared.status_code == 303
    assert cleared.headers["location"] == "/ctadmin/dashboard"
    principal = SessionCodec(
        get_settings().ctadmin_session_secret.get_secret_value(),
        get_settings().ctadmin_session_ttl_seconds,
    ).decode(client.cookies.get("ctadmin_session"))
    assert principal.persona_id == "ctadmin"
    assert "Choose an employee perspective" in client.get("/ctadmin/my-findings").text


@pytest.mark.parametrize(
    "return_to",
    [
        "/ctadmin/../outside",
        "/ctadmin/%2e%2e/outside",
        "/ctadmin/%252e%252e/outside",
        "/ctadmin/folder%5c..%5c..%5coutside",
    ],
)
def test_persona_action_rejects_decoded_traversal_return_paths(app_client, return_to):
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)

    response = client.post(
        "/ctadmin/actions/persona",
        data={
            "persona_id": "EMP-1",
            "csrf_token": _csrf(client),
            "return_to": return_to,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/ctadmin/dashboard"


def test_stale_signed_persona_is_labeled_and_can_be_cleared(app_client):
    """Removing an employee after selection must not trap the operator in a stale session."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_persona_route_data(data_dir)
    _login(client)
    client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    employees = json.loads((data_dir / "hr_employees.json").read_text())
    employees[0]["status"] = "terminated"
    employees[0]["terminated_at"] = "2026-08-08T00:00:00+00:00"
    (data_dir / "hr_employees.json").write_text(json.dumps(employees))

    page = client.get("/ctadmin/my-findings")

    assert page.status_code == 200
    assert "Selected perspective is no longer active" in page.text
    assert "EMP-1" in page.text
    assert "Clear employee perspective" in page.text
    cleared = client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    assert "Choose an employee perspective" in client.get("/ctadmin/my-findings").text


def test_my_findings_api_scopes_exactly_and_include_all_controls_terminal_rows(app_client):
    """Persona JSON must not leak another employee and must expose terminal work deliberately."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)
    client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    active = client.get("/ctadmin/api/my-findings")
    complete = client.get("/ctadmin/api/my-findings/", params={"include_all": "true"})

    assert active.status_code == 200
    assert {row["violationId"] for row in active.json()["rows"]} == {"VIO-100", "VIO-101"}
    assert active.json()["kpis"]["resolvedFindings"] == 0
    assert complete.status_code == 200
    assert {row["violationId"] for row in complete.json()["rows"]} == {
        "VIO-100",
        "VIO-101",
        "VIO-103",
    }
    assert complete.json()["kpis"]["openFindings"] == 1
    assert complete.json()["kpis"]["pendingApprovalFindings"] == 1
    assert complete.json()["kpis"]["resolvedFindings"] == 1
    assert "VIO-102" not in complete.text
    assert "VIO-200" not in complete.text


def test_persona_selection_scopes_only_my_findings_not_portfolio_pages(app_client):
    """A demo perspective must not silently narrow administrative portfolio surfaces."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)
    selected = client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert selected.status_code == 303

    dashboard_api = client.get("/ctadmin/api/dashboard")
    assert dashboard_api.status_code == 200
    assert dashboard_api.json()["kpis"]["totalFindings"] == 3
    assert {row["violationId"] for row in dashboard_api.json()["rows"]} == {
        "VIO-100",
        "VIO-101",
        "VIO-200",
    }

    dashboard_page = client.get("/ctadmin/dashboard")
    assert dashboard_page.status_code == 200
    embedded = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>',
        dashboard_page.text,
        re.DOTALL,
    )
    assert embedded is not None
    dashboard_payload = json.loads(embedded.group(1))
    assert dashboard_payload["kpis"]["totalFindings"] == 3
    assert {row["violationId"] for row in dashboard_payload["rows"]} == {
        "VIO-100",
        "VIO-101",
        "VIO-200",
    }

    remediation = client.get("/ctadmin/remediation")
    assert remediation.status_code == 200
    assert "Repair queue / 5 matching findings" in remediation.text
    assert "VIO-200" in remediation.text
    assert "VIO-102" in remediation.text

    my_findings = client.get("/ctadmin/api/my-findings")
    assert my_findings.status_code == 200
    assert my_findings.json()["kpis"]["totalFindings"] == 2
    assert {row["violationId"] for row in my_findings.json()["rows"]} == {
        "VIO-100",
        "VIO-101",
    }


def test_my_findings_api_guards_both_slash_forms_methods_and_include_all_values(app_client):
    """Concrete persona JSON routes may not fall through to redirects or wildcard semantics."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    for suffix in ["", "/"]:
        unauthenticated = client.get(f"/ctadmin/api/my-findings{suffix}", follow_redirects=False)
        assert unauthenticated.status_code == 401

    _login(client)
    client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    for suffix in ["", "/"]:
        assert client.post(f"/ctadmin/api/my-findings{suffix}").status_code == 404
    invalid = client.get("/ctadmin/api/my-findings", params={"include_all": "sometimes"})
    assert invalid.status_code == 422


def test_selected_my_findings_renders_identity_charts_filters_table_and_repair(app_client):
    """The selected page must be a complete persona dashboard, not an identity-only shell."""
    client, _ = app_client
    _seed_persona_route_data(get_settings().data_dir)
    _login(client)
    client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-1", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    response = client.get("/ctadmin/my-findings")

    assert response.status_code == 200
    for expected in [
        "Casey Example",
        "operations",
        "tech ops",
        "Open",
        "Pending approval",
        "Resolved",
        "chart-severity",
        "chart-rule",
        "finding-search",
        "findings-results",
        "repair-drawer",
        'data-api-endpoint="/ctadmin/api/my-findings"',
        'data-page-path="/ctadmin/my-findings"',
        'data-include-all="true"',
    ]:
        assert expected in response.text
    embedded = re.search(
        r'<script id="dashboard-data" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert embedded is not None
    payload = json.loads(embedded.group(1))
    assert payload["kpis"]["resolvedFindings"] == 1
    assert {row["violationId"] for row in payload["rows"]} == {
        "VIO-100",
        "VIO-101",
        "VIO-103",
    }


def test_selected_persona_with_zero_findings_renders_positive_clean_state(app_client):
    """A true zero-result perspective is verified clean, not a failed or filtered dashboard."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_persona_route_data(data_dir)
    employees = json.loads((data_dir / "hr_employees.json").read_text())
    employees.append(
        {
            "id": "EMP-CLEAN",
            "full_name": "Avery Clean",
            "email": "avery@example.com",
            "current_role": "auditor",
            "current_division": "risk",
            "status": "active",
            "role_history": [],
            "manager_id": None,
            "hired_at": "2026-01-01T00:00:00+00:00",
            "terminated_at": None,
        }
    )
    (data_dir / "hr_employees.json").write_text(json.dumps(employees))
    _login(client)
    client.post(
        "/ctadmin/actions/persona",
        data={"persona_id": "EMP-CLEAN", "csrf_token": _csrf(client)},
        follow_redirects=False,
    )

    response = client.get("/ctadmin/my-findings")

    assert response.status_code == 200
    assert 'id="persona-clean-state"' in response.text
    clean_tag = re.search(r'<section id="persona-clean-state"([^>]*)>', response.text)
    assert clean_tag is not None
    assert "hidden" not in clean_tag.group(1)
    assert "No entitlement-quality findings in this perspective" in response.text

    filtered = client.get("/ctadmin/my-findings", params={"severity": "high"})
    filtered_tag = re.search(r'<section id="persona-clean-state"([^>]*)>', filtered.text)
    assert filtered_tag is not None
    assert "hidden" in filtered_tag.group(1)
