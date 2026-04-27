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
