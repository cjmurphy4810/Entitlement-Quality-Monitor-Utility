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


def test_dashboard_action_tick_requires_auth(app_client, tmp_path):
    """Issue #3: dashboard actions must require bearer token."""
    client, _ = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": "Bearer test-token"})
    # Without token: 401
    r = client.post("/dashboard/actions/tick", follow_redirects=False)
    assert r.status_code == 401
    # With token: 303 redirect (success)
    r = client.post("/dashboard/actions/tick",
                    headers={"Authorization": "Bearer test-token"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_dashboard_action_reset_requires_auth(app_client):
    client, _ = app_client
    r = client.post("/dashboard/actions/reset", follow_redirects=False)
    assert r.status_code == 401


def test_dashboard_action_scenario_requires_auth(app_client, tmp_path):
    client, _ = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": "Bearer test-token"})
    r = client.post("/dashboard/actions/scenario",
                    data={"name": "kitchen_sink"},
                    follow_redirects=False)
    assert r.status_code == 401
