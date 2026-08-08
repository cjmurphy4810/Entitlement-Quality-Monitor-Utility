"""Atomic JSON persistence for the data fabric files."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class JsonStore:
    """Atomic, async, per-file-locked JSON store."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        self._transaction_lock = asyncio.Lock()
        self._cache: dict[str, Any] = {}

    def _lock_for(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    async def read(self, name: str) -> list[dict] | dict:
        if name in self._cache:
            return self._cache[name]
        path = self.data_dir / name
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        self._cache[name] = data
        return data

    async def write(self, name: str, data: list[dict] | dict) -> None:
        async with self._transaction_lock, self._lock_for(name):
            path = self.data_dir / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            os.replace(tmp, path)
            self._cache[name] = data

    async def write_many(
        self, documents: dict[str, list[dict] | dict]
    ) -> None:
        async with self._transaction_lock:
            staged: dict[str, Path] = {}
            backups: dict[str, Path] = {}
            originals: dict[str, bytes | None] = {}
            replacement_started = False

            try:
                for name, data in documents.items():
                    path = self.data_dir / name
                    payload = json.dumps(data, indent=2, default=str).encode()
                    staged[name] = self._stage_bytes(path, payload, ".stage")

                for name in documents:
                    path = self.data_dir / name
                    if path.exists():
                        originals[name] = path.read_bytes()
                        backups[name] = self._stage_bytes(
                            path, originals[name], ".backup"
                        )
                    else:
                        originals[name] = None

                replacement_started = True
                for name in documents:
                    os.replace(staged[name], self.data_dir / name)

                self._cleanup_artifacts((*staged.values(), *backups.values()))
            except Exception as primary_error:
                recovery_errors: list[Exception] = []
                preserved_backups: set[Path] = set()
                if replacement_started:
                    rollback_errors, preserved_backups = self._restore_documents(
                        documents, backups, originals
                    )
                    recovery_errors.extend(rollback_errors)

                recovery_errors.extend(
                    self._cleanup_after_failure(
                        (*staged.values(), *backups.values()),
                        preserved_backups,
                    )
                )
                if recovery_errors:
                    raise ExceptionGroup(
                        "write_many failed and recovery was incomplete",
                        [primary_error, *recovery_errors],
                    ) from primary_error
                raise

            self._cache.update(documents)

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
        except Exception:
            temporary_path.unlink(missing_ok=True)
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

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)
