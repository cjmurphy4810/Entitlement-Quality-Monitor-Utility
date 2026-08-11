from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runbook_documents_required_fly_volume_initialization():
    runbook = (PROJECT_ROOT / "docs/ctadmin-dashboard.md").read_text()

    for expected in [
        "POST /simulate/reset",
        "Authorization: Bearer ${EQM_DEPLOY_API_TOKEN}",
        "Content-Type: application/json",
        "--data '{\"small\": false}'",
        "all five JSON files",
        "before the first CTADMIN visit",
        "scripts/deploy.sh",
        "does not set CTADMIN secrets",
    ]:
        assert expected in runbook


def test_readme_and_runbook_describe_api_auth_boundary_exactly():
    readme = (PROJECT_ROOT / "README.md").read_text()
    runbook = (PROJECT_ROOT / "docs/ctadmin-dashboard.md").read_text()

    for document in [readme, runbook]:
        assert "Read routes are unauthenticated" in document
        assert "writes, simulation, and sync" in document
    assert "bearer-authenticated API" not in readme
