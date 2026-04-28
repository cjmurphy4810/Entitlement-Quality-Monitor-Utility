"""End-to-end happy path: reset → scenario → poll violations → transition → patch → resolved."""


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


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
