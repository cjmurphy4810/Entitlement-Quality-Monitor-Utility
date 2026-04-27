def test_dashboard_root(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "EQM" in body
    assert "Overview" in body
    # Demo control bar present
    assert "Inject scenario" in body or "scenario" in body.lower()
    # Counts visible
    assert "Entitlements" in body


def test_dashboard_static_css(app_client):
    client, _ = app_client
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "body" in r.text.lower()


def test_entitlements_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/entitlements")
    assert r.status_code == 200
    assert "Tier" in r.text


def test_hr_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/hr")
    assert r.status_code == 200
    assert "Role" in r.text


def test_cmdb_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/cmdb")
    assert r.status_code == 200
    assert "Criticality" in r.text


def test_violations_tab_groups_by_severity(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    client.post("/simulate/scenario", json={"name": "kitchen_sink"},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/violations")
    assert r.status_code == 200
    body = r.text
    for sev in ["critical", "high", "medium", "low"]:
        assert sev in body.lower()
