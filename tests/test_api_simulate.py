import json


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_simulate_reset_creates_seed(app_client, tmp_path):
    client, token = app_client
    r = client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    assert r.status_code == 200
    body = r.json()
    assert "entitlements" in body
    ents = json.loads((tmp_path / "entitlements.json").read_text())
    assert len(ents) > 0


def test_simulate_tick_runs_drift(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/tick", headers=_hdrs(token))
    assert r.status_code == 200
    assert "tick_number" in r.json()


def test_simulate_scenario(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/scenario",
                    json={"name": "terminated_user_with_admin"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["new_violations"] >= 1


def test_simulate_unknown_scenario(app_client):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/scenario", json={"name": "nope"},
                    headers=_hdrs(token))
    assert r.status_code == 400
