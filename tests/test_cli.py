import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args, env_overrides):
    env = {**os.environ, "EQM_BEARER_TOKEN": "t",
           "EQM_GIT_PUSH_ENABLED": "0"}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-m", "eqm", *args],
                          capture_output=True, text=True, env=env)


def test_cli_seed_creates_files(tmp_path: Path):
    res = _run(["seed", "--small"], {"EQM_DATA_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json",
              "assignments.json", "violations.json"]:
        assert (tmp_path / n).exists()
    ents = json.loads((tmp_path / "entitlements.json").read_text())
    assert len(ents) > 0


def test_cli_drift_runs_engine(tmp_path: Path):
    _run(["seed", "--small"], {"EQM_DATA_DIR": str(tmp_path)})
    res = _run(["drift"], {"EQM_DATA_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr
    vios = json.loads((tmp_path / "violations.json").read_text())
    assert isinstance(vios, list)
