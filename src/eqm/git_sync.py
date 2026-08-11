"""Git integration for the data fabric — commit + push (and pull on demand)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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


async def _run_thread_to_completion(
    function: Callable[..., bool], *args: object
) -> tuple[bool, asyncio.CancelledError | None]:
    """Keep a non-cancellable thread inside its transaction until it finishes."""
    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(worker)
            return result, cancellation
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.uncancel()
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise


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
            committed, cancellation = await _run_thread_to_completion(
                self._commit_data_locked, message
            )
            if cancellation is not None:
                raise cancellation
            return committed

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
            pushed, cancellation = await _run_thread_to_completion(self._push_now_locked)
            if cancellation is not None:
                raise cancellation
            return pushed

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
            pulled, cancellation = await _run_thread_to_completion(self._pull_now_locked)
            if pulled:
                store.invalidate()
                for name in CANONICAL_DATA_FILES:
                    await store.read(name)
            if cancellation is not None:
                raise cancellation
            return pulled

    def _pull_now_locked(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.pull()
        return True
