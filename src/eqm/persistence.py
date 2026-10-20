"""Recoverable JSON persistence for the data fabric files."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

_JOURNAL_NAME = ".jsonstore-transaction.json"
_LOCK_NAME = ".jsonstore.lock"


class ConcurrentWriteError(RuntimeError):
    """Raised when a cached snapshot changed before it could be written."""


class _TransactionCoordinator:
    """Process-local coordination shared by stores for one resolved directory."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.owner: asyncio.Task[Any] | None = None
        self.depth = 0
        self.versions: dict[str, int] = {}


_COORDINATORS: weakref.WeakValueDictionary[Path, _TransactionCoordinator] = (
    weakref.WeakValueDictionary()
)


class JsonStore:
    """Atomic JSON store with shared transactions and crash recovery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        coordinator = _COORDINATORS.get(self.data_dir)
        if coordinator is None:
            coordinator = _TransactionCoordinator()
            _COORDINATORS[self.data_dir] = coordinator
        self._coordinator = coordinator
        self._cache: dict[str, Any] = {}
        self._cache_versions: dict[str, int] = {}
        self._cache_fingerprints: dict[str, tuple[bool, str | None]] = {}
        self._defer_recovery_for_cached_reads = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Hold this directory's reentrant coordination boundary."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("JsonStore transactions require an asyncio task.")

        coordinator = self._coordinator
        if coordinator.owner is task:
            coordinator.depth += 1
            try:
                yield
            finally:
                coordinator.depth -= 1
            return

        await coordinator.lock.acquire()
        file_lock: int | None = None
        try:
            file_lock = await self._acquire_file_lock()
            coordinator.owner = task
            coordinator.depth = 1
            self._recover_if_needed()
            yield
        finally:
            coordinator.depth = 0
            coordinator.owner = None
            if file_lock is not None:
                self._release_file_lock(file_lock)
            coordinator.lock.release()

    async def read(self, name: str) -> list[dict] | dict:
        version = self._version(name)
        if (
            self._defer_recovery_for_cached_reads
            and name in self._cache
            and self._cache_versions.get(name) == version
        ):
            return self._cache[name]
        async with self.transaction():
            version = self._version(name)
            path = self.data_dir / name
            fingerprint = self._fingerprint(path)
            if (
                name in self._cache
                and self._cache_versions.get(name) == version
                and self._cache_fingerprints.get(name) == fingerprint
            ):
                return self._cache[name]
            if not path.exists():
                data: list[dict] | dict = []
            else:
                data = json.loads(path.read_text())
            self._cache[name] = data
            self._cache_versions[name] = version
            self._cache_fingerprints[name] = fingerprint
            return data

    async def write(self, name: str, data: list[dict] | dict) -> None:
        async with self.transaction():
            self._assert_snapshot_current((name,))
            path = self.data_dir / name
            payload = json.dumps(data, indent=2, default=str).encode()
            staged = self._stage_bytes(path, payload, ".tmp")
            try:
                os.replace(staged, path)
                self._fsync_directory()
            except Exception as primary_error:
                cleanup_errors = self._cleanup_after_failure((staged,), set())
                if cleanup_errors:
                    raise ExceptionGroup(
                        "write failed and temporary cleanup failed",
                        [primary_error, *cleanup_errors],
                    ) from primary_error
                raise
            self._record_commit({name: data})

    async def write_many(self, documents: dict[str, list[dict] | dict]) -> None:
        async with self.transaction():
            self._assert_snapshot_current(tuple(documents))
            self._write_many_locked(documents)

    def _write_many_locked(self, documents: dict[str, list[dict] | dict]) -> None:
        staged: dict[str, Path] = {}
        backups: dict[str, Path] = {}
        originals: dict[str, bytes | None] = {}
        journal: dict[str, object] | None = None
        journal_written = False
        replacement_started = False

        try:
            payloads: dict[str, bytes] = {}
            for name, data in documents.items():
                path = self.data_dir / name
                payload = json.dumps(data, indent=2, default=str).encode()
                payloads[name] = payload
                staged[name] = self._stage_bytes(path, payload, ".stage")

            for name in documents:
                path = self.data_dir / name
                if path.exists():
                    originals[name] = path.read_bytes()
                    backups[name] = self._stage_bytes(path, originals[name], ".backup")
                else:
                    originals[name] = None

            journal = self._build_journal(documents, staged, backups, originals, payloads)
            try:
                self._write_journal(journal)
            except Exception:
                journal_written = self._journal_path.exists()
                raise
            else:
                journal_written = True

            replacement_started = True
            for name in documents:
                os.replace(staged[name], self.data_dir / name)
            self._fsync_directory()

            self._cleanup_artifacts((*staged.values(), *backups.values()))
            self._remove_journal()
        except Exception as primary_error:
            recovery_errors: list[Exception] = []
            preserved_backups: set[Path] = set()

            if journal_written and journal is not None:
                try:
                    journal["state"] = "rollback"
                    self._write_journal(journal)
                except Exception as journal_error:
                    recovery_errors.append(journal_error)
                else:
                    if replacement_started:
                        rollback_errors, preserved_backups = self._restore_documents(
                            documents, backups, originals
                        )
                        recovery_errors.extend(rollback_errors)
                        try:
                            self._fsync_directory()
                        except Exception as fsync_error:
                            recovery_errors.append(fsync_error)

                    recovery_errors.extend(
                        self._cleanup_after_failure(
                            (*staged.values(), *backups.values()),
                            preserved_backups,
                        )
                    )
                    if not recovery_errors:
                        try:
                            self._remove_journal()
                        except Exception as journal_cleanup_error:
                            recovery_errors.append(journal_cleanup_error)
            else:
                recovery_errors.extend(
                    self._cleanup_after_failure(
                        (*staged.values(), *backups.values()),
                        preserved_backups,
                    )
                )

            if recovery_errors:
                self._defer_recovery_for_cached_reads = True
                raise ExceptionGroup(
                    "write_many failed and recovery was incomplete",
                    [primary_error, *recovery_errors],
                ) from primary_error
            raise

        self._record_commit(documents)

    def _assert_snapshot_current(self, names: tuple[str, ...]) -> None:
        for name in names:
            expected = self._cache_versions.get(name)
            version_changed = expected is not None and expected != self._version(name)
            fingerprint_changed = (
                name in self._cache_fingerprints
                and self._cache_fingerprints[name]
                != self._fingerprint(self.data_dir / name)
            )
            if version_changed or fingerprint_changed:
                raise ConcurrentWriteError(
                    f"{name} changed since it was read; reload before writing."
                )

    def _record_commit(self, documents: dict[str, list[dict] | dict]) -> None:
        for name, data in documents.items():
            version = self._version(name) + 1
            self._coordinator.versions[name] = version
            self._cache[name] = data
            self._cache_versions[name] = version
            self._cache_fingerprints[name] = self._fingerprint(
                self.data_dir / name
            )

    def _version(self, name: str) -> int:
        return self._coordinator.versions.get(name, 0)

    def _build_journal(
        self,
        documents: dict[str, list[dict] | dict],
        staged: dict[str, Path],
        backups: dict[str, Path],
        originals: dict[str, bytes | None],
        payloads: dict[str, bytes],
    ) -> dict[str, object]:
        entries: list[dict[str, object]] = []
        for name in documents:
            original = originals[name]
            entries.append(
                {
                    "name": name,
                    "stage": str(staged[name].relative_to(self.data_dir)),
                    "new_sha256": self._hash_bytes(payloads[name]),
                    "existed": original is not None,
                    "backup": (
                        str(backups[name].relative_to(self.data_dir))
                        if original is not None
                        else None
                    ),
                    "old_sha256": (self._hash_bytes(original) if original is not None else None),
                }
            )
        return {"version": 1, "state": "forward", "entries": entries}

    @property
    def _journal_path(self) -> Path:
        return self.data_dir / _JOURNAL_NAME

    def _write_journal(self, journal: dict[str, object]) -> None:
        payload = json.dumps(journal, indent=2, sort_keys=True).encode()
        staged = self._stage_bytes(self._journal_path, payload, ".journal")
        try:
            os.replace(staged, self._journal_path)
            self._fsync_directory()
        except Exception as primary_error:
            cleanup_errors = self._cleanup_after_failure((staged,), set())
            if cleanup_errors:
                raise ExceptionGroup(
                    "journal write failed and temporary cleanup failed",
                    [primary_error, *cleanup_errors],
                ) from primary_error
            raise

    def _remove_journal(self) -> None:
        self._journal_path.unlink(missing_ok=True)
        self._fsync_directory()

    def _recover_if_needed(self) -> None:
        if not self._journal_path.exists():
            self._defer_recovery_for_cached_reads = False
            return

        journal = self._load_journal()
        state = journal["state"]
        entries = journal["entries"]
        assert isinstance(state, str)
        assert isinstance(entries, list)

        if state == "forward":
            for entry in entries:
                self._recover_forward_entry(entry)
        else:
            for entry in entries:
                self._recover_rollback_entry(entry)

        self._fsync_directory()
        artifacts = tuple(
            artifact for entry in entries for artifact in self._entry_artifacts(entry)
        )
        self._cleanup_artifacts(artifacts)
        self._remove_journal()

        for entry in entries:
            name = entry["name"]
            assert isinstance(name, str)
            self._coordinator.versions[name] = self._version(name) + 1
        self._defer_recovery_for_cached_reads = False

    def _load_journal(self) -> dict[str, object]:
        try:
            raw = json.loads(self._journal_path.read_text())
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError("unsupported journal version")
            if raw.get("state") not in {"forward", "rollback"}:
                raise ValueError("invalid journal state")
            entries = raw.get("entries")
            if not isinstance(entries, list) or not entries:
                raise ValueError("journal entries must be a non-empty list")
            for entry in entries:
                self._validate_journal_entry(entry)
        except Exception as error:
            raise RuntimeError("JSON transaction journal is invalid.") from error
        return raw

    def _validate_journal_entry(self, entry: object) -> None:
        if not isinstance(entry, dict):
            raise ValueError("journal entry must be an object")
        required_strings = ("name", "stage", "new_sha256")
        if any(not isinstance(entry.get(key), str) for key in required_strings):
            raise ValueError("journal entry is missing required strings")
        if not isinstance(entry.get("existed"), bool):
            raise ValueError("journal entry existed flag is invalid")
        if entry["existed"] and (
            not isinstance(entry.get("backup"), str) or not isinstance(entry.get("old_sha256"), str)
        ):
            raise ValueError("journal entry is missing original metadata")
        for key in ("name", "stage", "backup"):
            value = entry.get(key)
            if value is not None:
                self._journal_member(value)

    def _recover_forward_entry(self, entry: dict[str, object]) -> None:
        name = entry["name"]
        stage_name = entry["stage"]
        new_digest = entry["new_sha256"]
        assert isinstance(name, str)
        assert isinstance(stage_name, str)
        assert isinstance(new_digest, str)
        destination = self._journal_member(name)
        if self._path_matches(destination, new_digest):
            return
        stage = self._journal_member(stage_name)
        if not self._path_matches(stage, new_digest):
            raise RuntimeError(f"Cannot roll forward transaction file {name}.")
        os.replace(stage, destination)

    def _recover_rollback_entry(self, entry: dict[str, object]) -> None:
        name = entry["name"]
        assert isinstance(name, str)
        destination = self._journal_member(name)
        if entry["existed"] is False:
            destination.unlink(missing_ok=True)
            return

        backup_name = entry["backup"]
        old_digest = entry["old_sha256"]
        assert isinstance(backup_name, str)
        assert isinstance(old_digest, str)
        if self._path_matches(destination, old_digest):
            return
        backup = self._journal_member(backup_name)
        if not self._path_matches(backup, old_digest):
            raise RuntimeError(f"Cannot roll back transaction file {name}.")
        os.replace(backup, destination)

    def _entry_artifacts(self, entry: dict[str, object]) -> tuple[Path, ...]:
        paths = [self._journal_member(entry["stage"])]
        backup = entry.get("backup")
        if backup is not None:
            paths.append(self._journal_member(backup))
        return tuple(paths)

    def _journal_member(self, relative_name: object) -> Path:
        if not isinstance(relative_name, str):
            raise ValueError("journal path must be a string")
        candidate = (self.data_dir / relative_name).resolve()
        try:
            candidate.relative_to(self.data_dir)
        except ValueError as error:
            raise ValueError("journal path escapes the data directory") from error
        return candidate

    @staticmethod
    def _hash_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def _path_matches(cls, path: Path, digest: str) -> bool:
        return path.exists() and cls._hash_bytes(path.read_bytes()) == digest

    @classmethod
    def _fingerprint(cls, path: Path) -> tuple[bool, str | None]:
        if not path.exists():
            return (False, None)
        return (True, cls._hash_bytes(path.read_bytes()))

    @property
    def _lock_path(self) -> Path:
        return self.data_dir / _LOCK_NAME

    async def _acquire_file_lock(self) -> int:
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(
                        descriptor,
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    return descriptor
                except BlockingIOError:
                    await asyncio.sleep(0.01)
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _release_file_lock(descriptor: int) -> None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @staticmethod
    def _stage_bytes(path: Path, payload: bytes, suffix: str) -> Path:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=suffix,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
        except Exception as staging_error:
            try:
                temporary_path.unlink(missing_ok=True)
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "staging failed and temporary cleanup failed",
                    [staging_error, cleanup_error],
                ) from staging_error
            raise
        return temporary_path

    def _restore_documents(
        self,
        documents: dict[str, list[dict] | dict],
        backups: dict[str, Path],
        originals: dict[str, bytes | None],
    ) -> tuple[list[Exception], set[Path]]:
        rollback_errors: list[Exception] = []
        preserved_backups: set[Path] = set()
        for name in documents:
            path = self.data_dir / name
            try:
                original = originals[name]
                if original is not None:
                    backup = backups[name]
                    if not backup.exists():
                        backup = self._stage_bytes(path, original, ".backup")
                        backups[name] = backup
                    os.replace(backup, path)
                else:
                    path.unlink(missing_ok=True)
            except Exception as error:
                rollback_errors.append(error)
                if name in backups and backups[name].exists():
                    preserved_backups.add(backups[name])
        return rollback_errors, preserved_backups

    @staticmethod
    def _cleanup_artifacts(artifacts: tuple[Path, ...]) -> None:
        for artifact in artifacts:
            artifact.unlink(missing_ok=True)

    @staticmethod
    def _cleanup_after_failure(
        artifacts: tuple[Path, ...], preserved: set[Path]
    ) -> list[Exception]:
        cleanup_errors: list[Exception] = []
        for artifact in artifacts:
            if artifact in preserved:
                continue
            try:
                artifact.unlink(missing_ok=True)
            except Exception as error:
                cleanup_errors.append(error)
        return cleanup_errors

    def _fsync_directory(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(self.data_dir, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
            self._cache_versions.clear()
            self._cache_fingerprints.clear()
        else:
            self._cache.pop(name, None)
            self._cache_versions.pop(name, None)
            self._cache_fingerprints.pop(name, None)
