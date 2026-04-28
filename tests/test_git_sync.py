import subprocess
from pathlib import Path

from eqm.git_sync import GitSync


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
    (local_dir / "data" / "seed.json").write_text("[]")
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
    (local / "data" / "x.json").write_text('[{"a": 1}]')
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
