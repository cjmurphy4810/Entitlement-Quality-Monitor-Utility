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
         "target_type": "employee", "target_id": "EMP-1",
         "explanation": "...", "evidence": {}, "recommended_action": "auto_revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))

    body = client.get("/api/user-findings?userId=EMP-1").json()
    assert len(body["data"]) == 1
    assert body["data"][0]["violationId"] == "VIO-1"
