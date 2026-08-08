"""Git integration for the data fabric — commit + push (and pull on demand)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from git import Repo

from eqm.persistence import JsonStore

CANONICAL_DATA_FILES = (
    "entitlements.json",
    "hr_employees.json",
    "cmdb_resources.json",
    "assignments.json",
    "violations.json",
)


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
        return asyncio.run(self.acommit_data(message))

    async def acommit_data(self, message: str) -> bool:
        store = JsonStore(self.repo_dir / self.data_subdir)
        async with store.transaction():
            return await asyncio.to_thread(self._commit_data_locked, message)

    def _commit_data_locked(self, message: str) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        paths = [
            (Path(self.data_subdir) / name).as_posix()
            for name in CANONICAL_DATA_FILES
        ]
        repo.git.add("--", *paths)
        staged = repo.git.diff("--cached", "--name-only", "--", *paths)
        if not staged.strip():
            return False
        repo.git.commit("--only", "-m", message, "--", *paths)
        return True

    def push_now(self) -> bool:
        return asyncio.run(self.apush_now())

    async def apush_now(self) -> bool:
        store = JsonStore(self.repo_dir / self.data_subdir)
        async with store.transaction():
            return await asyncio.to_thread(self._push_now_locked)

    def _push_now_locked(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.push()
        return True

    def pull_now(self) -> bool:
        return asyncio.run(self.apull_now())

    async def apull_now(self) -> bool:
        store = JsonStore(self.repo_dir / self.data_subdir)
        async with store.transaction():
            pulled = await asyncio.to_thread(self._pull_now_locked)
            if not pulled:
                return False
            store.invalidate()
            for name in CANONICAL_DATA_FILES:
                await store.read(name)
            return True

    def _pull_now_locked(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.pull()
        return True
