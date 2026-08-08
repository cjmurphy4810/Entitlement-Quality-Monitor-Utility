import asyncio
import subprocess
from pathlib import Path

import pytest

from eqm.git_sync import GitSync
from eqm.persistence import JsonStore

CANONICAL_FILES = (
    "entitlements.json",
    "hr_employees.json",
    "cmdb_resources.json",
    "assignments.json",
    "violations.json",
)


def _init_remote(remote_dir: Path) -> None:
    remote_dir.mkdir()
    subprocess.run(["git", "init", "--bare", "-b", "main"], cwd=remote_dir,
                   check=True, capture_output=True)


def _init_local(local_dir: Path, remote_dir: Path) -> None:
    local_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=local_dir, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=local_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"],
                   cwd=local_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)],
                   cwd=local_dir, check=True)
    (local_dir / "data").mkdir()
    for name in CANONICAL_FILES:
        (local_dir / "data" / name).write_text("[]")
    subprocess.run(["git", "add", "."], cwd=local_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=local_dir, check=True,
                   capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local_dir,
                   check=True, capture_output=True)


def test_commit_and_push(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _init_remote(remote)
    _init_local(local, remote)
    sync = GitSync(repo_dir=local, data_subdir="data",
                   remote_url=None, push_enabled=True)
    (local / "data" / "entitlements.json").write_text('[{"a": 1}]')
    sync.commit_data("test commit")
    sync.push_now()
    # Verify the bare remote received it
    log = subprocess.check_output(
        ["git", "--git-dir", str(remote), "log", "--oneline"]).decode()
    assert "test commit" in log


def test_push_disabled_is_noop(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    sync = GitSync(repo_dir=local, data_subdir="data",
                   remote_url=None, push_enabled=False)
    # Should not raise — and not require a real repo.
    sync.commit_data("ignored")
    sync.push_now()


def test_commit_stages_only_canonical_data_files(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _init_remote(remote)
    _init_local(local, remote)
    data_dir = local / "data"
    (data_dir / "entitlements.json").write_text('[{"changed": true}]')
    for name in (
        ".jsonstore.lock",
        ".entitlements.json.deadbeef.journal",
        ".entitlements.json.deadbeef.stage",
        ".entitlements.json.deadbeef.backup",
        ".entitlements.json.tmp",
    ):
        (data_dir / name).write_text("control")
    subprocess.run(
        ["git", "add", "-f", "data/.jsonstore.lock"],
        cwd=local,
        check=True,
    )
    sync = GitSync(
        repo_dir=local,
        data_subdir="data",
        remote_url=None,
        push_enabled=True,
    )

    assert sync.commit_data("canonical only") is True

    committed = set(
        subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=local
        )
        .decode()
        .splitlines()
    )
    assert "data/entitlements.json" in committed
    assert not any(
        name.endswith((".lock", ".stage", ".backup", ".tmp"))
        or "transaction" in name
        for name in committed
    )


@pytest.mark.asyncio
async def test_commit_waits_for_inflight_json_transaction(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _init_remote(remote)
    _init_local(local, remote)
    data_dir = local / "data"
    (data_dir / "entitlements.json").write_text('[{"changed": true}]')
    sync = GitSync(local, "data", None, True)
    store = JsonStore(data_dir)

    async with store.transaction():
        commit_task = asyncio.create_task(sync.acommit_data("coordinated"))
        await asyncio.sleep(0.05)
        commit_waited = not commit_task.done()
    assert await commit_task is True
    assert commit_waited


@pytest.mark.asyncio
async def test_pull_waits_then_refreshes_cached_data(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    peer = tmp_path / "peer"
    _init_remote(remote)
    _init_local(local, remote)
    subprocess.run(["git", "clone", str(remote), str(peer)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "peer@example.com"], cwd=peer, check=True)
    subprocess.run(["git", "config", "user.name", "peer"], cwd=peer, check=True)
    (peer / "data" / "entitlements.json").write_text('[{"from": "peer"}]')
    subprocess.run(["git", "add", "data/entitlements.json"], cwd=peer, check=True)
    subprocess.run(["git", "commit", "-m", "peer update"], cwd=peer, check=True, capture_output=True)
    subprocess.run(["git", "push"], cwd=peer, check=True, capture_output=True)

    data_dir = local / "data"
    store = JsonStore(data_dir)
    assert await store.read("entitlements.json") == []
    sync = GitSync(local, "data", None, True)
    async with store.transaction():
        pull_task = asyncio.create_task(sync.apull_now())
        await asyncio.sleep(0.05)
        pull_waited = not pull_task.done()
    assert await pull_task is True

    assert pull_waited
    assert await store.read("entitlements.json") == [{"from": "peer"}]
