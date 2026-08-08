import asyncio
import json
import os
from pathlib import Path

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


async def test_write_many_updates_all_files_and_cached_reads(
    tmp_store: JsonStore, tmp_path
):
    await tmp_store.write("first.json", {"value": "old-first"})
    await tmp_store.write("second.json", [{"value": "old-second"}])

    new_first = {"value": "new-first"}
    new_second = [{"value": "new-second"}]
    await tmp_store.write_many(
        {"first.json": new_first, "second.json": new_second}
    )

    assert json.loads((tmp_path / "first.json").read_text()) == new_first
    assert json.loads((tmp_path / "second.json").read_text()) == new_second
    assert await tmp_store.read("first.json") is new_first
    assert await tmp_store.read("second.json") is new_second
    assert {path.name for path in tmp_path.iterdir()} == {
        "first.json",
        "second.json",
    }


async def test_write_many_rolls_back_disk_and_cache_when_second_replace_fails(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = [{"value": "old-second"}]
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)
    first_raw = (tmp_path / "first.json").read_text()
    second_raw = (tmp_path / "second.json").read_text()

    destination_replaces = 0
    real_replace = os.replace

    def fail_second_destination_replace(src, dst):
        nonlocal destination_replaces
        if Path(dst) in {
            tmp_path / "first.json",
            tmp_path / "second.json",
        }:
            destination_replaces += 1
            if destination_replaces == 2:
                raise OSError("injected second destination replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_second_destination_replace)

    with pytest.raises(
        OSError, match="injected second destination replace failure"
    ):
        await tmp_store.write_many(
            {
                "first.json": {"value": "new-first"},
                "second.json": [{"value": "new-second"}],
            }
        )

    assert (tmp_path / "first.json").read_text() == first_raw
    assert (tmp_path / "second.json").read_text() == second_raw
    assert await tmp_store.read("first.json") is old_first
    assert await tmp_store.read("second.json") is old_second
    assert {path.name for path in tmp_path.iterdir()} == {
        "first.json",
        "second.json",
    }


async def test_write_many_rolls_back_when_backup_cleanup_fails(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = [{"value": "old-second"}]
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)
    first_raw = (tmp_path / "first.json").read_text()
    second_raw = (tmp_path / "second.json").read_text()

    backup_unlinks = 0
    real_unlink = Path.unlink

    def fail_second_backup_cleanup(path, *args, **kwargs):
        nonlocal backup_unlinks
        if path.suffix == ".backup":
            backup_unlinks += 1
            if backup_unlinks == 2:
                raise OSError("injected backup cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second_backup_cleanup)

    with pytest.raises(OSError, match="injected backup cleanup failure"):
        await tmp_store.write_many(
            {
                "first.json": {"value": "new-first"},
                "second.json": [{"value": "new-second"}],
            }
        )

    assert (tmp_path / "first.json").read_text() == first_raw
    assert (tmp_path / "second.json").read_text() == second_raw
    assert await tmp_store.read("first.json") is old_first
    assert await tmp_store.read("second.json") is old_second
    assert {path.name for path in tmp_path.iterdir()} == {
        "first.json",
        "second.json",
    }


async def test_write_many_preserves_backup_and_both_errors_when_restore_fails(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = [{"value": "old-second"}]
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)

    real_replace = os.replace

    def fail_primary_replace_and_first_restore(src, dst):
        source = Path(src)
        destination = Path(dst)
        if source.suffix == ".stage" and destination.name == "second.json":
            raise OSError("injected destination replace failure")
        if source.suffix == ".backup" and destination.name == "first.json":
            raise OSError("injected rollback restoration failure")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_primary_replace_and_first_restore)

    with pytest.raises(ExceptionGroup) as exc_info:
        await tmp_store.write_many(
            {
                "first.json": {"value": "new-first"},
                "second.json": [{"value": "new-second"}],
            }
        )

    errors = exc_info.value.exceptions
    assert [str(error) for error in errors] == [
        "injected destination replace failure",
        "injected rollback restoration failure",
    ]
    assert json.loads((tmp_path / "first.json").read_text()) == {
        "value": "new-first"
    }
    assert json.loads((tmp_path / "second.json").read_text()) == old_second
    assert await tmp_store.read("first.json") is old_first
    assert await tmp_store.read("second.json") is old_second

    backup_paths = [
        path for path in tmp_path.iterdir() if path.suffix == ".backup"
    ]
    assert len(backup_paths) == 1
    assert json.loads(backup_paths[0].read_text()) == old_first
