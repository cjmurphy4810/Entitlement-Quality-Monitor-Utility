import json


def _seed_files(tmp_path):
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "x", "pbl_description": "A long enough description here.",
         "access_tier": 2, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00", "updated_at": "2025-01-01T00:00:00+00:00"}
    ]))
    (tmp_path / "hr_employees.json").write_text(json.dumps([
        {"id": "EMP-1", "full_name": "x", "email": "x@example.com",
         "current_role": "operations", "current_division": "tech_ops",
         "status": "active", "role_history": [],
         "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
         "terminated_at": None}
    ]))
    (tmp_path / "cmdb_resources.json").write_text(json.dumps([
        {"id": "RES-1", "name": "x", "type": "application",
         "criticality": "low", "owner_division": "tech_ops",
         "environment": "prod", "linked_entitlement_ids": [], "description": "x"}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    (tmp_path / "violations.json").write_text("[]")


def test_get_entitlements(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    r = client.get("/entitlements")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "ENT-1"


def test_get_entitlement_by_id_404(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    assert client.get("/entitlements/MISSING").status_code == 404


def test_get_entitlement_filters(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    r = client.get("/entitlements?division=hr")
    assert r.status_code == 200
    assert r.json() == []


def test_get_violations_filter_state(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-01-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))
    r = client.get("/violations?state=open")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert client.get("/violations?state=resolved").json() == []


def test_get_hr_and_cmdb(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    assert client.get("/hr/employees").status_code == 200
    assert client.get("/hr/employees/EMP-1").status_code == 200
    assert client.get("/cmdb/resources").status_code == 200
    assert client.get("/cmdb/resources/RES-1").status_code == 200
    assert client.get("/assignments?employee_id=EMP-1").status_code == 200


def test_get_violations_since_with_naive_timestamp(app_client, tmp_path):
    """Issue #1: ?since with naive ISO timestamp should not crash."""
    import json
    client, _ = app_client
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")
    # Naive timestamp (no offset) — should be treated as UTC and not crash.
    r = client.get("/violations?since=2026-01-01T00:00:00")
    assert r.status_code == 200
    assert len(r.json()) == 1
    # Z-suffix should also work.
    r = client.get("/violations?since=2026-05-01T00:00:00Z")
    assert r.status_code == 200
    assert r.json() == []  # detected_at is in April


def test_flagged_records_default_returns_open_and_pending(app_client, tmp_path):
    """Appian view: defaults to open + pending_approval, includes user context for assignment-target violations."""
    import json
    client, _ = app_client
    (tmp_path / "hr_employees.json").write_text(json.dumps([
        {"id": "EMP-1", "full_name": "Alice Demo", "email": "alice@example.com",
         "current_role": "operations", "current_division": "tech_ops",
         "status": "active", "role_history": [],
         "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00", "terminated_at": None}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "HR-04", "rule_name": "Terminated user holds active assignment",
         "severity": "critical", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "assignment", "target_id": "ASN-1",
         "explanation": "x", "evidence": {}, "recommended_action": "auto_revoke_assignment",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None},
        {"id": "VIO-2", "rule_id": "ENT-Q-01", "rule_name": "PBL completeness",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "resolved", "workflow_history": [],
         "appian_case_id": None},
    ]))
    for n in ["entitlements.json", "cmdb_resources.json"]:
        (tmp_path / n).write_text("[]")

    r = client.get("/api/flagged-records")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    # VIO-2 is resolved → excluded by default
    assert len(body["data"]) == 1
    rec = body["data"][0]
    assert rec["userId"] == "EMP-1"
    assert rec["userName"] == "Alice Demo"
    assert rec["severity"] == "Critical"
    assert rec["status"] == "Open"
    assert rec["ruleId"] == "HR-04"


def test_flagged_records_severity_filter(app_client, tmp_path):
    import json
    client, _ = app_client
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")
    assert len(client.get("/api/flagged-records?severity=critical").json()["data"]) == 0
    assert len(client.get("/api/flagged-records?severity=low").json()["data"]) == 1


def test_flagged_records_include_all(app_client, tmp_path):
    """include_all=true returns every state, not just open + pending_approval."""
    import json
    client, _ = app_client
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "resolved", "workflow_history": [],
         "appian_case_id": None},
        {"id": "VIO-2", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-2",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "rejected", "workflow_history": [],
         "appian_case_id": None},
    ]))
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")
    # Default: filtered out
    assert client.get("/api/flagged-records").json()["data"] == []
    # include_all=true: both returned
    assert len(client.get("/api/flagged-records?include_all=true").json()["data"]) == 2


def test_flagged_record_detail(app_client, tmp_path):
    """/api/flagged-records/{vid} returns single record with evidence + history."""
    import json
    client, _ = app_client
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "HR-04", "rule_name": "Terminated user holds active assignment",
         "severity": "critical", "detected_at": "2026-04-01T00:00:00+00:00",
         "target_type": "assignment", "target_id": "ASN-1",
         "explanation": "Bob is terminated", "evidence": {"terminated_at": "2026-03-15"},
         "recommended_action": "auto_revoke_assignment",
         "suggested_fix": {"_action": "delete_assignment"},
         "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")
    r = client.get("/api/flagged-records/VIO-1")
    assert r.status_code == 200
    body = r.json()
    assert body["violationId"] == "VIO-1"
    assert body["evidence"] == {"terminated_at": "2026-03-15"}
    assert body["suggestedFix"] == {"_action": "delete_assignment"}
    assert body["workflowHistory"] == []
    # 404 for unknown
    assert client.get("/api/flagged-records/MISSING").status_code == 404
