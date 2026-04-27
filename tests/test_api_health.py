def test_health_endpoint(app_client):
    client, _ = app_client
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_protected_endpoint_requires_token(app_client):
    client, _ = app_client
    r = client.post("/simulate/tick")
    assert r.status_code == 401


def test_protected_endpoint_with_token(app_client):
    client, token = app_client
    r = client.post("/simulate/tick", headers={"Authorization": f"Bearer {token}"})
    # Endpoint may return 200 or 422 depending on later wiring;
    # for skeleton we accept any non-401.
    assert r.status_code != 401
