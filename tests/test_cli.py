import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eqm.cli import _save_bundle
from eqm.persistence import JsonStore
from eqm.seed import SeedBundle


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


@pytest.mark.asyncio
async def test_save_bundle_uses_one_five_file_write_many_call():
    class RecordingStore:
        def __init__(self):
            self.calls = []

        async def write_many(self, documents):
            self.calls.append(documents)

    store = RecordingStore()
    bundle = SeedBundle(
        entitlements=[],
        hr_employees=[],
        cmdb_resources=[],
        assignments=[],
    )

    await _save_bundle(store, bundle, [])

    assert len(store.calls) == 1
    assert set(store.calls[0]) == {
        "entitlements.json",
        "hr_employees.json",
        "cmdb_resources.json",
        "assignments.json",
        "violations.json",
    }


@pytest.mark.asyncio
async def test_save_bundle_recovers_all_five_files_after_crash(
    tmp_path: Path, monkeypatch
):
    names = (
        "entitlements.json",
        "hr_employees.json",
        "cmdb_resources.json",
        "assignments.json",
        "violations.json",
    )
    for name in names:
        (tmp_path / name).write_text('[{"old": true}]')
    store = JsonStore(tmp_path)
    bundle = SeedBundle(
        entitlements=[],
        hr_employees=[],
        cmdb_resources=[],
        assignments=[],
    )
    real_replace = os.replace
    destination_replaces = 0

    class SimulatedCrash(BaseException):
        pass

    def crash_during_second_replacement(src, dst):
        nonlocal destination_replaces
        if Path(dst).name in names:
            destination_replaces += 1
            if destination_replaces == 2:
                raise SimulatedCrash("CLI process stopped during bundle save")
        real_replace(src, dst)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(os, "replace", crash_during_second_replacement)
        with pytest.raises(SimulatedCrash, match="bundle save"):
            await _save_bundle(store, bundle, [])

    fresh_store = JsonStore(tmp_path)
    for name in names:
        assert await fresh_store.read(name) == []
