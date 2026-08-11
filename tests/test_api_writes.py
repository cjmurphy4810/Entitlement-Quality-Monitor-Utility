import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from eqm.api import (
    ReopenRequest,
    TransitionRequest,
    _load_bundle,
    _patch_record,
    _save_bundle_and_evaluate,
    revoke_assignment,
    violation_reopen,
    violation_transition,
)
from eqm.models import Entitlement, WorkflowState
from eqm.persistence import JsonStore
from eqm.seed import SeedBundle


def _seed(tmp_path):
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "old", "pbl_description": "Long enough description here for tests.",
         "access_tier": 2, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00", "updated_at": "2025-01-01T00:00:00+00:00"}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    for n in ["hr_employees.json", "cmdb_resources.json", "violations.json"]:
        (tmp_path / n).write_text("[]")


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def _violation(state: str) -> dict:
    return {
        "id": "VIO-1",
        "rule_id": "ENT-Q-01",
        "rule_name": "PBL completeness",
        "severity": "low",
        "detected_at": "2026-01-01T00:00:00+00:00",
        "target_type": "entitlement",
        "target_id": "ENT-1",
        "explanation": "Description is incomplete.",
        "evidence": {},
        "recommended_action": "update_entitlement_field",
        "suggested_fix": {"pbl_description": "fixed"},
        "workflow_state": state,
        "workflow_history": [],
        "appian_case_id": None,
    }


class _OuterTransactionStore(JsonStore):
    def __init__(self, data_dir):
        super().__init__(data_dir)
        self.outer_depth = 0

    @asynccontextmanager
    async def transaction(self):
        self.outer_depth += 1
        try:
            async with super().transaction():
                yield
        finally:
            self.outer_depth -= 1

    async def read(self, name):
        assert self.outer_depth > 0, f"{name} was read outside the API transaction"
        return await super().read(name)

    async def write(self, name, data):
        assert self.outer_depth > 0, f"{name} was written outside the API transaction"
        await super().write(name, data)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["patch", "revoke", "transition", "reopen"])
async def test_bearer_read_modify_write_holds_outer_transaction(
    tmp_path, operation
):
    _seed(tmp_path)
    if operation in {"transition", "reopen"}:
        state = "rejected" if operation == "reopen" else "open"
        (tmp_path / "violations.json").write_text(json.dumps([_violation(state)]))
    store = _OuterTransactionStore(tmp_path)

    if operation == "patch":
        await _patch_record(
            store,
            "entitlements.json",
            "ENT-1",
            {"name": "updated"},
            {"name"},
            Entitlement,
        )
    elif operation == "revoke":
        await revoke_assignment("ASN-1", store)
    elif operation == "transition":
        await violation_transition(
            "VIO-1",
            TransitionRequest(
                to_state=WorkflowState.PENDING_APPROVAL,
                actor="tester",
            ),
            store,
        )
    else:
        await violation_reopen(
            "VIO-1",
            ReopenRequest(actor="tester", note="Re-evaluate finding."),
            store,
        )


@pytest.mark.asyncio
async def test_patch_transaction_rejects_concurrent_stale_writer(
    tmp_path, monkeypatch
):
    _seed(tmp_path)
    patch_store = JsonStore(tmp_path)
    stale_store = JsonStore(tmp_path)
    stale = await stale_store.read("entitlements.json")
    assert isinstance(stale, list)
    stale[0]["pbl_description"] = "A different stale bearer update."
    write_reached = asyncio.Event()
    release_write = asyncio.Event()
    actual_write = patch_store.write

    async def pause_before_write(name, data):
        write_reached.set()
        await release_write.wait()
        await actual_write(name, data)

    monkeypatch.setattr(patch_store, "write", pause_before_write)
    patch_task = asyncio.create_task(
        _patch_record(
            patch_store,
            "entitlements.json",
            "ENT-1",
            {"name": "patched atomically"},
            {"name"},
            Entitlement,
        )
    )
    await write_reached.wait()
    stale_task = asyncio.create_task(
        stale_store.write("entitlements.json", stale)
    )
    await asyncio.sleep(0)
    stale_writer_waited = not stale_task.done()

    release_write.set()
    patched = await patch_task
    if stale_writer_waited:
        with pytest.raises(RuntimeError, match="changed since it was read"):
            await stale_task
    else:
        await stale_task

    assert stale_writer_waited
    assert patched["name"] == "patched atomically"
    saved = json.loads((tmp_path / "entitlements.json").read_text())
    assert saved[0]["name"] == "patched atomically"
    assert saved[0]["pbl_description"] == "Long enough description here for tests."


class _AtomicBundleStore(_OuterTransactionStore):
    def __init__(self, data_dir):
        super().__init__(data_dir)
        self.write_many_calls = 0
        self.written_names = set()

    async def write(self, name, data):
        raise AssertionError(f"bundle persistence used single-file write for {name}")

    async def write_many(self, documents):
        assert self.outer_depth > 0
        self.write_many_calls += 1
        self.written_names = set(documents)
        await super().write_many(documents)


@pytest.mark.asyncio
async def test_bundle_save_is_one_five_file_transaction(tmp_path):
    _seed(tmp_path)
    store = _AtomicBundleStore(tmp_path)
    bundle = SeedBundle(
        entitlements=[],
        hr_employees=[],
        cmdb_resources=[],
        assignments=[],
    )

    new_count = await _save_bundle_and_evaluate(store, bundle)

    assert new_count == 0
    assert store.write_many_calls == 1
    assert store.written_names == {
        "entitlements.json",
        "hr_employees.json",
        "cmdb_resources.json",
        "assignments.json",
        "violations.json",
    }


@pytest.mark.asyncio
async def test_load_bundle_cannot_return_hybrid_snapshot(tmp_path, monkeypatch):
    _seed(tmp_path)
    load_store = JsonStore(tmp_path)
    writer = JsonStore(tmp_path)
    assignments = await writer.read("assignments.json")
    assignments[0]["active"] = False
    actual_read = load_store.read
    first_file_read = asyncio.Event()
    release_load = asyncio.Event()

    async def pause_after_entitlements(name):
        data = await actual_read(name)
        if name == "entitlements.json":
            first_file_read.set()
            await release_load.wait()
        return data

    monkeypatch.setattr(load_store, "read", pause_after_entitlements)
    load_task = asyncio.create_task(_load_bundle(load_store))
    await first_file_read.wait()
    writer_task = asyncio.create_task(writer.write("assignments.json", assignments))
    await asyncio.sleep(0)
    writer_waited = not writer_task.done()

    release_load.set()
    bundle = await load_task
    await writer_task

    assert writer_waited
    assert len(bundle.entitlements) == 1
    assert bundle.assignments[0].active is True


def test_patch_entitlement(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "new"}, headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["name"] == "new"
    saved = json.loads((tmp_path / "entitlements.json").read_text())
    assert saved[0]["name"] == "new"


def test_patch_entitlement_unknown_field_rejected(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"not_a_field": 1}, headers=_hdrs(token))
    assert r.status_code == 400


def test_patch_entitlement_requires_auth(app_client, tmp_path):
    client, _ = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "x"})
    assert r.status_code == 401


def test_delete_assignment(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.delete("/assignments/ASN-1", headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json() == {"id": "ASN-1", "active": False}
    saved = json.loads((tmp_path / "assignments.json").read_text())
    assert saved[0]["active"] is False
