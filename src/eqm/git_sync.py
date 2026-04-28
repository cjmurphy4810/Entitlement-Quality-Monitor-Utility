"""Git integration for the data fabric — commit + push (and pull on demand)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git import Repo


@dataclass(slots=True)
class GitSync:
    repo_dir: Path
    data_subdir: str
    remote_url: str | None
    push_enabled: bool

    def _repo(self) -> Repo | None:
        if not self.push_enabled:
            return None
        try:
            return Repo(str(self.repo_dir))
        except Exception:
            return None

    def commit_data(self, message: str) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        repo.git.add(self.data_subdir)
        if not repo.is_dirty(untracked_files=True, path=self.data_subdir):
            return False
        repo.index.commit(message)
        return True

    def push_now(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.push()
        return True

    def pull_now(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.pull()
        return True
