import json


def _seed_violation(tmp_path, state="open"):
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-01-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {},
         "recommended_action": "update_entitlement_field",
         "suggested_fix": {"pbl_description": "fixed"},
         "workflow_state": state, "workflow_history": [],
         "appian_case_id": None}
    ]))
    for n in ["entitlements.json", "hr_employees.json",
              "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_transition_open_to_pending(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "pending_approval", "actor": "appian"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "pending_approval"


def test_illegal_transition_returns_409(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "approved", "actor": "x"},
                    headers=_hdrs(token))
    assert r.status_code == 409
    assert "legal" in r.json()["detail"].lower() or "Legal" in r.json()["detail"]


def test_reject_requires_note(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "pending_approval")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "rejected", "actor": "alice"},
                    headers=_hdrs(token))
    assert r.status_code == 400


def test_approved_to_resolved_path(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "pending_approval")
    client.post("/violations/VIO-1/transition",
                json={"to_state": "approved", "actor": "alice", "note": "ok"},
                headers=_hdrs(token))
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "resolved", "actor": "system"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "resolved"


def test_reopen_rejected(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "rejected")
    r = client.post("/violations/VIO-1/reopen",
                    json={"actor": "compliance",
                          "note": "circumstances changed"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "open"


def test_reopen_only_for_rejected(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/reopen",
                    json={"actor": "x", "note": "x"},
                    headers=_hdrs(token))
    assert r.status_code == 409
