import asyncio
import json

import pytest

from eqm.persistence import JsonStore


@pytest.fixture
def tmp_store(tmp_path) -> JsonStore:
    return JsonStore(tmp_path)


async def test_write_then_read(tmp_store: JsonStore):
    await tmp_store.write("entitlements.json", [{"id": "ENT-1"}])
    data = await tmp_store.read("entitlements.json")
    assert data == [{"id": "ENT-1"}]


async def test_read_missing_returns_empty(tmp_store: JsonStore):
    assert await tmp_store.read("missing.json") == []


async def test_write_is_atomic(tmp_store: JsonStore, tmp_path):
    await tmp_store.write("x.json", [{"a": 1}])
    # No leftover temp file
    siblings = list(tmp_path.iterdir())
    assert all(p.suffix != ".tmp" for p in siblings)
    # Content is valid JSON, not partial
    raw = (tmp_path / "x.json").read_text()
    assert json.loads(raw) == [{"a": 1}]


async def test_concurrent_writes_serialize(tmp_store: JsonStore):
    async def writer(n):
        await tmp_store.write("c.json", [{"n": n}])
    await asyncio.gather(*(writer(i) for i in range(20)))
    data = await tmp_store.read("c.json")
    assert isinstance(data, list)
    assert len(data) == 1  # last write wins, file is intact
