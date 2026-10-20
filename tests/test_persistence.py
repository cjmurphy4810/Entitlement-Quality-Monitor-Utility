import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from eqm.persistence import JsonStore


@pytest.fixture
def tmp_store(tmp_path) -> JsonStore:
    return JsonStore(tmp_path)


def _store_artifact_names(tmp_path: Path) -> set[str]:
    return {
        path.name
        for path in tmp_path.iterdir()
        if path.name != ".jsonstore.lock"
    }


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


async def test_two_store_transaction_rejects_a_stale_waiting_writer(tmp_path):
    transaction_store = JsonStore(tmp_path)
    ordinary_store = JsonStore(tmp_path)
    await transaction_store.write(
        "records.json",
        [{"id": "REC-1", "repair": False, "ordinary": False}],
    )
    stale_records = await ordinary_store.read("records.json")
    assert isinstance(stale_records, list)
    stale_records[0]["ordinary"] = True
    assert hasattr(transaction_store, "transaction")

    transaction_started = asyncio.Event()
    release_transaction = asyncio.Event()

    async def commit_repair() -> None:
        async with transaction_store.transaction():
            transaction_store.invalidate("records.json")
            records = await transaction_store.read("records.json")
            assert isinstance(records, list)
            records[0]["repair"] = True
            transaction_started.set()
            await release_transaction.wait()
            await transaction_store.write("records.json", records)

    repair_task = asyncio.create_task(commit_repair())
    await transaction_started.wait()
    ordinary_task = asyncio.create_task(ordinary_store.write("records.json", stale_records))
    await asyncio.sleep(0)
    writer_waited = not ordinary_task.done()

    release_transaction.set()
    await repair_task
    if writer_waited:
        with pytest.raises(RuntimeError, match="changed since it was read"):
            await ordinary_task
    else:
        await ordinary_task

    assert writer_waited
    fresh = JsonStore(tmp_path)
    assert await fresh.read("records.json") == [{"id": "REC-1", "repair": True, "ordinary": False}]


async def test_transaction_waits_for_another_process_using_same_directory(tmp_path):
    ready = tmp_path / "other-process-ready"
    release = tmp_path / "release-other-process"
    script = """
import asyncio
import sys
from pathlib import Path
from eqm.persistence import JsonStore

async def main():
    data_dir, ready, release = map(Path, sys.argv[1:])
    async with JsonStore(data_dir).transaction():
        ready.write_text("ready")
        while not release.exists():
            await asyncio.sleep(0.01)

asyncio.run(main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), str(ready), str(release)]
    )
    writer_task = None
    try:
        for _ in range(500):
            if ready.exists():
                break
            if process.poll() is not None:
                raise AssertionError("lock-holder process exited before becoming ready")
            await asyncio.sleep(0.01)
        assert ready.exists()

        writer_task = asyncio.create_task(
            JsonStore(tmp_path).write("cross-process.json", {"value": "written"})
        )
        await asyncio.sleep(0.05)
        writer_waited = not writer_task.done()
        release.write_text("release")
        await asyncio.wait_for(writer_task, timeout=5)
        process.wait(timeout=5)
    finally:
        release.write_text("release")
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    assert writer_waited


async def test_write_rejects_snapshot_changed_by_another_process(tmp_path):
    store = JsonStore(tmp_path)
    await store.write("records.json", [{"id": "REC-1", "value": "initial"}])
    stale_records = await store.read("records.json")
    assert isinstance(stale_records, list)
    stale_records[0]["value"] = "stale overwrite"
    script = """
import asyncio
import sys
from pathlib import Path
from eqm.persistence import JsonStore

asyncio.run(
    JsonStore(Path(sys.argv[1])).write(
        "records.json", [{"id": "REC-1", "value": "external update"}]
    )
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr

    with pytest.raises(RuntimeError, match="changed since it was read"):
        await store.write("records.json", stale_records)

    assert json.loads((tmp_path / "records.json").read_text()) == [
        {"id": "REC-1", "value": "external update"}
    ]


async def test_write_many_updates_all_files_and_cached_reads(tmp_store: JsonStore, tmp_path):
    await tmp_store.write("first.json", {"value": "old-first"})
    await tmp_store.write("second.json", [{"value": "old-second"}])

    new_first = {"value": "new-first"}
    new_second = [{"value": "new-second"}]
    await tmp_store.write_many({"first.json": new_first, "second.json": new_second})

    assert json.loads((tmp_path / "first.json").read_text()) == new_first
    assert json.loads((tmp_path / "second.json").read_text()) == new_second
    assert await tmp_store.read("first.json") is new_first
    assert await tmp_store.read("second.json") is new_second
    assert _store_artifact_names(tmp_path) == {
        "first.json",
        "second.json",
    }


async def test_fresh_store_rolls_forward_after_crash_between_replacements(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = {"value": "old-second"}
    new_first = {"value": "new-first"}
    new_second = {"value": "new-second"}
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)
    real_replace = os.replace

    class SimulatedCrash(BaseException):
        pass

    def crash_before_second_replacement(src, dst):
        source = Path(src)
        destination = Path(dst)
        if source.suffix == ".stage" and destination.name == "second.json":
            raise SimulatedCrash("process stopped during replacement")
        real_replace(src, dst)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(os, "replace", crash_before_second_replacement)
        with pytest.raises(SimulatedCrash, match="during replacement"):
            await tmp_store.write_many({"first.json": new_first, "second.json": new_second})

    fresh_store = JsonStore(tmp_path)
    assert await fresh_store.read("first.json") == new_first
    assert await fresh_store.read("second.json") == new_second
    assert _store_artifact_names(tmp_path) == {
        "first.json",
        "second.json",
    }


async def test_fresh_store_finishes_rollback_after_crash_during_recovery(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = {"value": "old-second"}
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)
    real_replace = os.replace

    class SimulatedCrash(BaseException):
        pass

    def fail_commit_then_crash_during_rollback(src, dst):
        source = Path(src)
        destination = Path(dst)
        if source.suffix == ".stage" and destination.name == "second.json":
            raise OSError("injected commit failure")
        if source.suffix == ".backup" and destination.name == "first.json":
            raise SimulatedCrash("process stopped during rollback")
        real_replace(src, dst)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            os,
            "replace",
            fail_commit_then_crash_during_rollback,
        )
        with pytest.raises(SimulatedCrash, match="during rollback"):
            await tmp_store.write_many(
                {
                    "first.json": {"value": "new-first"},
                    "second.json": {"value": "new-second"},
                }
            )

    fresh_store = JsonStore(tmp_path)
    assert await fresh_store.read("first.json") == old_first
    assert await fresh_store.read("second.json") == old_second
    assert _store_artifact_names(tmp_path) == {
        "first.json",
        "second.json",
    }


async def test_journal_fsync_failure_rolls_back_prepared_transaction(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    old_first = {"value": "old-first"}
    old_second = {"value": "old-second"}
    await tmp_store.write("first.json", old_first)
    await tmp_store.write("second.json", old_second)
    real_fsync = os.fsync
    fsync_calls = 0

    def fail_journal_directory_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 6:
            raise OSError("injected journal directory fsync failure")
        real_fsync(descriptor)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(os, "fsync", fail_journal_directory_fsync)
        with pytest.raises(OSError, match="injected journal directory fsync failure"):
            await tmp_store.write_many(
                {
                    "first.json": {"value": "new-first"},
                    "second.json": {"value": "new-second"},
                }
            )

    fresh_store = JsonStore(tmp_path)
    assert await fresh_store.read("first.json") == old_first
    assert await fresh_store.read("second.json") == old_second
    assert _store_artifact_names(tmp_path) == {
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

    with pytest.raises(OSError, match="injected second destination replace failure"):
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
    assert _store_artifact_names(tmp_path) == {
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
    assert _store_artifact_names(tmp_path) == {
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
    assert json.loads((tmp_path / "first.json").read_text()) == {"value": "new-first"}
    assert json.loads((tmp_path / "second.json").read_text()) == old_second
    assert await tmp_store.read("first.json") is old_first
    assert await tmp_store.read("second.json") is old_second

    backup_paths = [path for path in tmp_path.iterdir() if path.suffix == ".backup"]
    assert len(backup_paths) == 1
    assert json.loads(backup_paths[0].read_text()) == old_first


async def test_write_many_removes_stage_when_fsync_fails(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    def fail_fsync(_descriptor):
        raise OSError("injected staging fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="injected staging fsync failure"):
        await tmp_store.write_many({"first.json": {"value": "new-first"}})

    assert _store_artifact_names(tmp_path) == set()
    assert await tmp_store.read("first.json") == []


async def test_write_many_surfaces_fsync_and_stage_cleanup_failures(
    tmp_store: JsonStore, tmp_path, monkeypatch
):
    real_unlink = Path.unlink

    def fail_fsync(_descriptor):
        raise OSError("injected staging fsync failure")

    def fail_stage_cleanup(path, *args, **kwargs):
        if path.suffix == ".stage":
            raise OSError("injected staging cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", fail_fsync)
    monkeypatch.setattr(Path, "unlink", fail_stage_cleanup)

    with pytest.raises(ExceptionGroup) as exc_info:
        await tmp_store.write_many({"first.json": {"value": "new-first"}})

    assert [str(error) for error in exc_info.value.exceptions] == [
        "injected staging fsync failure",
        "injected staging cleanup failure",
    ]
    stage_paths = [path for path in tmp_path.iterdir() if path.suffix == ".stage"]
    assert len(stage_paths) == 1
    assert json.loads(stage_paths[0].read_text()) == {"value": "new-first"}
    assert await tmp_store.read("first.json") == []
