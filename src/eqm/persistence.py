"""Atomic JSON persistence for the data fabric files."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


class JsonStore:
    """Atomic, async, per-file-locked JSON store."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
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
        async with self._lock_for(name):
            path = self.data_dir / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            os.replace(tmp, path)
            self._cache[name] = data

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)
