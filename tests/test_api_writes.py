import json


def _seed(tmp_path):
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "old", "pbl_description": "Long enough description here for tests.",
         "access_tier": 2, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00", "updated_at": "2025-01-01T00:00:00+00:00"}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    for n in ["hr_employees.json", "cmdb_resources.json", "violations.json"]:
        (tmp_path / n).write_text("[]")


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_patch_entitlement(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "new"}, headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["name"] == "new"
    saved = json.loads((tmp_path / "entitlements.json").read_text())
    assert saved[0]["name"] == "new"


def test_patch_entitlement_unknown_field_rejected(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"not_a_field": 1}, headers=_hdrs(token))
    assert r.status_code == 400


def test_patch_entitlement_requires_auth(app_client, tmp_path):
    client, _ = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "x"})
    assert r.status_code == 401


def test_delete_assignment(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.delete("/assignments/ASN-1", headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json() == {"id": "ASN-1", "active": False}
    saved = json.loads((tmp_path / "assignments.json").read_text())
    assert saved[0]["active"] is False
