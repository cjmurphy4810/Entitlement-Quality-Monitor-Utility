from pathlib import Path

from eqm.config import Settings


def test_settings_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    s = Settings()
    assert s.data_dir == tmp_path
    assert s.bearer_token == "test-token"
    assert s.git_push_enabled is False
    assert s.entitlements_path == tmp_path / "entitlements.json"
    assert s.violations_path == tmp_path / "violations.json"


def test_settings_requires_bearer_token(monkeypatch, tmp_path):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EQM_BEARER_TOKEN", raising=False)
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings()
