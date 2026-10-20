import pytest
from fastapi.testclient import TestClient

from eqm.config import get_settings


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("EQM_GIT_PUSH_ENABLED", "0")
    monkeypatch.setenv("EQM_CTADMIN_USERNAME", "demo-admin")
    monkeypatch.setenv("EQM_CTADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.setenv("EQM_CTADMIN_SESSION_SECRET", "test-session-secret-at-least-32-bytes")
    monkeypatch.setenv("EQM_CTADMIN_SECURE_COOKIES", "0")
    get_settings.cache_clear()
    # Seed empty files so reads succeed.
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json",
              "assignments.json", "violations.json"]:
        (tmp_path / n).write_text("[]")
    from eqm.api import app
    return TestClient(app), "test-token"
