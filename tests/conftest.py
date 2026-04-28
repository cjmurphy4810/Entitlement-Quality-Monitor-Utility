import pytest
from fastapi.testclient import TestClient

from eqm.config import get_settings


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("EQM_GIT_PUSH_ENABLED", "0")
    get_settings.cache_clear()
    # Seed empty files so reads succeed.
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json",
              "assignments.json", "violations.json"]:
        (tmp_path / n).write_text("[]")
    from eqm.api import app
    return TestClient(app), "test-token"
