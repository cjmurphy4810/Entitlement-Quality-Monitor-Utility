"""End-to-end happy paths through the API and CTADMIN operator surface."""

import json

from eqm.config import get_settings
from eqm.ctadmin.auth import SessionCodec


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def _ctadmin_csrf(client) -> str:
    settings = get_settings()
    session = client.cookies.get("ctadmin_session")
    assert session is not None
    return SessionCodec(
        settings.ctadmin_session_secret.get_secret_value(),
        settings.ctadmin_session_ttl_seconds,
    ).decode(session).csrf_token


def _seed_ctadmin_happy_path(data_dir) -> None:
    """Write one deterministic, persona-scoped PBL finding and no incidental findings."""
    documents = {
        "entitlements.json": [
            {
                "id": "ENT-E2E-1",
                "name": "Ledger Reader",
                "pbl_description": "bad",
                "access_tier": 3,
                "acceptable_roles": ["operations"],
                "division": "tech_ops",
                "linked_resource_ids": ["RES-E2E-1"],
                "sod_tags": [],
                "created_at": "2026-08-07T12:00:00+00:00",
                "updated_at": "2026-08-07T12:00:00+00:00",
            }
        ],
        "hr_employees.json": [
            {
                "id": "EMP-E2E-1",
                "full_name": "Casey Operator",
                "email": "casey@example.com",
                "current_role": "operations",
                "current_division": "tech_ops",
                "status": "active",
                "role_history": [],
                "manager_id": None,
                "hired_at": "2025-01-01T00:00:00+00:00",
                "terminated_at": None,
            }
        ],
        "cmdb_resources.json": [
            {
                "id": "RES-E2E-1",
                "name": "Ledger API",
                "type": "api",
                "criticality": "low",
                "owner_division": "tech_ops",
                "environment": "prod",
                "linked_entitlement_ids": ["ENT-E2E-1"],
                "description": "Ledger API for approved operations workflows.",
            }
        ],
        "assignments.json": [
            {
                "id": "ASN-E2E-1",
                "employee_id": "EMP-E2E-1",
                "entitlement_id": "ENT-E2E-1",
                "granted_at": "2026-01-01T00:00:00+00:00",
                "granted_by": "ctadmin-demo",
                "last_certified_at": "2026-07-01T00:00:00+00:00",
                "active": True,
            }
        ],
        "violations.json": [
            {
                "id": "VIO-E2E-1",
                "rule_id": "ENT-Q-01",
                "rule_name": "PBL completeness",
                "severity": "low",
                "detected_at": "2026-08-07T12:00:00+00:00",
                "target_type": "entitlement",
                "target_id": "ENT-E2E-1",
                "explanation": "PBL description fails completeness check: length=3 < 20",
                "evidence": {
                    "pbl_description": "bad",
                    "reasons": ["length=3 < 20"],
                },
                "recommended_action": "update_entitlement_field",
                "suggested_fix": {
                    "pbl_description": (
                        "Provides approved ledger access for operations reconciliation."
                    )
                },
                "workflow_state": "open",
                "workflow_history": [],
                "appian_case_id": None,
            }
        ],
    }
    for name, records in documents.items():
        (data_dir / name).write_text(json.dumps(records))


def test_full_remediation_flow(app_client):
    client, token = app_client

    # 1. Reset to clean seed
    r = client.post("/simulate/reset", json={"small": True}, headers=_hdrs(token))
    assert r.status_code == 200

    # 2. Inject a CRITICAL scenario
    r = client.post("/simulate/scenario",
                    json={"name": "terminated_user_with_admin"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["new_violations"] >= 1

    # 3. Poll for the critical violation
    r = client.get("/violations?state=open&severity=critical")
    assert r.status_code == 200
    crit = r.json()
    assert len(crit) >= 1
    target = next(v for v in crit if v["rule_id"] == "HR-04")

    # 4. Transition to pending_approval (Appian picks it up)
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "pending_approval", "actor": "appian"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 5. Apply suggested fix: revoke the assignment
    asn_id = target["target_id"]
    r = client.delete(f"/assignments/{asn_id}", headers=_hdrs(token))
    assert r.status_code == 200

    # 6. Transition to approved
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "approved", "actor": "alice@example.com",
                          "note": "Verified termination, revoked"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 7. Transition to resolved
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "resolved", "actor": "system"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 8. Verify workflow history captured every transition
    r = client.get(f"/violations/{target['id']}")
    final = r.json()
    states = [h["to_state"] for h in final["workflow_history"]]
    assert states == ["pending_approval", "approved", "resolved"]

    # 9. Now run an evaluate / drift tick — verify HR-04 violation does NOT
    #    re-fire for this assignment (because assignment.active is now False).
    r = client.post("/simulate/tick", headers=_hdrs(token))
    assert r.status_code == 200
    r = client.get("/violations?state=open")
    open_vios = r.json()
    re_detected = [v for v in open_vios if v["rule_id"] == "HR-04"
                   and v["target_id"] == asn_id]
    assert re_detected == []


def test_ctadmin_persona_repair_updates_source_and_dashboard_totals(app_client):
    """Exercise the authenticated UI contract through a verified persisted repair."""
    client, _ = app_client
    data_dir = get_settings().data_dir
    _seed_ctadmin_happy_path(data_dir)

    login = client.post(
        "/ctadmin/login",
        data={
            "username": "demo-admin",
            "password": "correct-horse-battery-staple",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/ctadmin/dashboard"

    dashboard_before = client.get("/ctadmin/api/dashboard")
    assert dashboard_before.status_code == 200
    assert dashboard_before.json()["kpis"] == {
        "totalAssignments": 1,
        "totalFindings": 1,
        "highCriticalFindings": 0,
        "catalogFindings": 1,
        "criticalFindings": 0,
        "highFindings": 0,
        "notStartedFindings": 1,
        "inProgressFindings": 0,
        "completeFindings": 0,
        "openFindings": 1,
        "pendingApprovalFindings": 0,
        "resolvedFindings": 0,
    }

    persona = client.post(
        "/ctadmin/actions/persona",
        data={
            "persona_id": "EMP-E2E-1",
            "return_to": "/ctadmin/my-findings",
            "csrf_token": _ctadmin_csrf(client),
        },
        follow_redirects=False,
    )
    assert persona.status_code == 303
    assert persona.headers["location"] == "/ctadmin/my-findings"

    my_findings_before = client.get("/ctadmin/api/my-findings")
    assert my_findings_before.status_code == 200
    assert my_findings_before.json()["kpis"]["totalFindings"] == 1
    assert my_findings_before.json()["rows"][0]["violationId"] == "VIO-E2E-1"

    detail = client.get("/ctadmin/findings/VIO-E2E-1")
    assert detail.status_code == 200
    assert "PBL completeness" in detail.text
    assert "Preview repair" in detail.text

    preview = client.get("/ctadmin/api/findings/VIO-E2E-1/repair-preview")
    assert preview.status_code == 200
    submission = preview.json()["submission"]
    submission["pbl_description"] = (
        "Provides approved ledger access for monthly operations reconciliation."
    )
    repair = client.post(
        "/ctadmin/actions/findings/VIO-E2E-1/repair",
        json=submission,
        headers={"X-CSRF-Token": _ctadmin_csrf(client)},
    )
    assert repair.status_code == 200
    assert repair.json()["cleared"] is True
    assert repair.json()["workflowState"] == "resolved"

    entitlements = json.loads((data_dir / "entitlements.json").read_text())
    assert entitlements[0]["pbl_description"] == submission["pbl_description"]
    violations = json.loads((data_dir / "violations.json").read_text())
    matching = [
        finding
        for finding in violations
        if (
            finding["rule_id"],
            finding["target_type"],
            finding["target_id"],
        )
        == ("ENT-Q-01", "entitlement", "ENT-E2E-1")
    ]
    assert len(matching) == 1
    assert matching[0]["workflow_state"] == "resolved"

    dashboard_after = client.get("/ctadmin/api/dashboard")
    assert dashboard_after.status_code == 200
    assert dashboard_after.json()["kpis"]["totalFindings"] == 0
    my_findings_after = client.get("/ctadmin/api/my-findings")
    assert my_findings_after.status_code == 200
    assert my_findings_after.json()["kpis"]["totalFindings"] == 0
    my_findings_complete = client.get(
        "/ctadmin/api/my-findings", params={"include_all": "true"}
    )
    assert my_findings_complete.status_code == 200
    assert my_findings_complete.json()["kpis"]["totalFindings"] == 1
    assert my_findings_complete.json()["kpis"]["resolvedFindings"] == 1
