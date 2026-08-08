from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eqm.ctadmin.repairs import RepairValidationError
from eqm.ctadmin.service import (
    RepairDidNotClearError,
    StaleFindingError,
    execute_repair,
)
from eqm.engine import EngineRunResult, run_engine
from eqm.models import (
    AccessTier,
    Assignment,
    CMDBResource,
    Criticality,
    Division,
    EmployeeStatus,
    Entitlement,
    HREmployee,
    ResourceType,
    Role,
    Violation,
    WorkflowState,
)
from eqm.persistence import JsonStore
from eqm.rules.base import DataSnapshot
from eqm.seed import SeedBundle

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
DATA_FILES = (
    "entitlements.json",
    "hr_employees.json",
    "cmdb_resources.json",
    "assignments.json",
    "violations.json",
)


def _entitlement(**changes: object) -> Entitlement:
    values: dict[str, object] = {
        "id": "ENT-1",
        "name": "Ledger reader",
        "pbl_description": "bad",
        "access_tier": AccessTier.GENERAL_RO,
        "acceptable_roles": [Role.OPERATIONS],
        "division": Division.TECH_OPS,
        "linked_resource_ids": ["RES-1"],
        "sod_tags": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return Entitlement(**values)


def _employee(**changes: object) -> HREmployee:
    values: dict[str, object] = {
        "id": "EMP-1",
        "full_name": "Casey Example",
        "email": "casey@example.com",
        "current_role": Role.OPERATIONS,
        "current_division": Division.TECH_OPS,
        "status": EmployeeStatus.ACTIVE,
        "role_history": [],
        "manager_id": None,
        "hired_at": NOW,
        "terminated_at": None,
    }
    values.update(changes)
    return HREmployee(**values)


def _resource(**changes: object) -> CMDBResource:
    values: dict[str, object] = {
        "id": "RES-1",
        "name": "Ledger API",
        "type": ResourceType.API,
        "criticality": Criticality.LOW,
        "owner_division": Division.TECH_OPS,
        "environment": "prod",
        "linked_entitlement_ids": ["ENT-1"],
        "description": "Finance ledger API",
    }
    values.update(changes)
    return CMDBResource(**values)


def _assignment(**changes: object) -> Assignment:
    values: dict[str, object] = {
        "id": "ASN-1",
        "employee_id": "EMP-1",
        "entitlement_id": "ENT-1",
        "granted_at": NOW,
        "granted_by": "system",
        "last_certified_at": None,
        "active": True,
    }
    values.update(changes)
    return Assignment(**values)


def _bundle(
    *,
    entitlements: list[Entitlement] | None = None,
    employees: list[HREmployee] | None = None,
    resources: list[CMDBResource] | None = None,
    assignments: list[Assignment] | None = None,
) -> SeedBundle:
    return SeedBundle(
        entitlements=entitlements if entitlements is not None else [_entitlement()],
        hr_employees=employees if employees is not None else [_employee()],
        cmdb_resources=resources if resources is not None else [_resource()],
        assignments=assignments if assignments is not None else [],
    )


async def _seed_store(tmp_path: Path, bundle: SeedBundle) -> tuple[JsonStore, list[Violation]]:
    store = JsonStore(tmp_path)
    result = run_engine(
        DataSnapshot(
            bundle.entitlements,
            bundle.hr_employees,
            bundle.cmdb_resources,
            bundle.assignments,
        ),
        existing_violations=[],
    )
    await store.write_many(
        {
            "entitlements.json": [item.model_dump(mode="json") for item in bundle.entitlements],
            "hr_employees.json": [item.model_dump(mode="json") for item in bundle.hr_employees],
            "cmdb_resources.json": [
                item.model_dump(mode="json") for item in bundle.cmdb_resources
            ],
            "assignments.json": [item.model_dump(mode="json") for item in bundle.assignments],
            "violations.json": [item.model_dump(mode="json") for item in result.violations],
        }
    )
    return store, result.violations


def _finding(violations: list[Violation], rule_id: str, target_id: str) -> Violation:
    return next(
        item
        for item in violations
        if item.rule_id == rule_id and item.target_id == target_id
    )


def _file_bytes(path: Path) -> dict[str, bytes]:
    return {name: (path / name).read_bytes() for name in DATA_FILES}


async def _replace_violations(store: JsonStore, violations: list[Violation]) -> None:
    await store.write(
        "violations.json",
        [item.model_dump(mode="json") for item in violations],
    )


@pytest.mark.asyncio
async def test_execute_repair_updates_data_resolves_finding_and_audits_actor(
    tmp_path: Path,
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    submission = {
        "pbl_description": "Provides read-only access to Ledger API for operations reporting."
    }

    receipt = await execute_repair(store, finding.id, "demo-admin", submission)

    assert receipt.cleared is True
    assert receipt.rule_id == "ENT-Q-01"
    assert (await store.read("entitlements.json"))[0]["pbl_description"] == submission[
        "pbl_description"
    ]
    reconciled = [Violation(**raw) for raw in await store.read("violations.json")]
    resolved = _finding(reconciled, "ENT-Q-01", "ENT-1")
    assert resolved.workflow_state.value == "resolved"
    audit = resolved.workflow_history[-1]
    assert audit.actor == "demo-admin"
    assert audit.override_fix is not None
    assert audit.override_fix["record_ids"] == ["ENT-1"]
    assert audit.override_fix["changes"] == [
        {
            "collection": "entitlements",
            "record_id": "ENT-1",
            "before": {"pbl_description": "bad"},
            "after": submission,
        }
    ]
    assert json.loads((tmp_path / "violations.json").read_text())[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submission",
    [
        {"pbl_description": "still bad"},
        {"pbl_description": "[Owner — please rewrite this description.]"},
    ],
)
async def test_invalid_pbl_is_rejected_without_changing_any_file(
    tmp_path: Path,
    submission: dict[str, object],
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    before = _file_bytes(tmp_path)

    with pytest.raises(RepairValidationError):
        await execute_repair(store, finding.id, "demo-admin", submission)

    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
async def test_mutated_evidence_is_rejected_without_changing_any_file(
    tmp_path: Path,
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    raw = await store.read("entitlements.json")
    assert isinstance(raw, list)
    raw[0]["pbl_description"] = "different stale value"
    await store.write("entitlements.json", raw)
    before = _file_bytes(tmp_path)

    with pytest.raises(StaleFindingError, match="evidence|stale"):
        await execute_repair(
            store,
            finding.id,
            "demo-admin",
            {
                "pbl_description": (
                    "Provides read-only access to Ledger API for operations reporting."
                )
            },
        )

    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
async def test_inactive_assignment_is_rejected_without_changing_any_file(
    tmp_path: Path,
) -> None:
    current = _bundle(
        employees=[
            _employee(status=EmployeeStatus.TERMINATED, terminated_at=NOW)
        ],
        assignments=[_assignment()],
    )
    store, violations = await _seed_store(tmp_path, current)
    finding = _finding(violations, "HR-04", "ASN-1")
    raw = await store.read("assignments.json")
    assert isinstance(raw, list)
    raw[0]["active"] = False
    await store.write("assignments.json", raw)
    before = _file_bytes(tmp_path)

    with pytest.raises(StaleFindingError, match="current|stale"):
        await execute_repair(store, finding.id, "demo-admin", {})

    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
async def test_missing_finding_is_typed_and_does_not_change_files(tmp_path: Path) -> None:
    store, _violations = await _seed_store(tmp_path, _bundle())
    before = _file_bytes(tmp_path)

    with pytest.raises(StaleFindingError, match="missing|ambiguous"):
        await execute_repair(store, "VIO-MISSING", "demo-admin", {})

    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [WorkflowState.RESOLVED, WorkflowState.REJECTED])
async def test_terminal_finding_is_typed_and_does_not_change_files(
    tmp_path: Path,
    state: WorkflowState,
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    finding.workflow_state = state
    await _replace_violations(store, violations)
    before = _file_bytes(tmp_path)

    with pytest.raises(StaleFindingError, match=state.value):
        await execute_repair(
            store,
            finding.id,
            "demo-admin",
            {
                "pbl_description": (
                    "Provides read-only access to Ledger API for operations reporting."
                )
            },
        )

    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
async def test_engine_nonclear_is_typed_and_does_not_change_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    before = _file_bytes(tmp_path)
    actual_run_engine = run_engine

    def preserve_target(
        snapshot: DataSnapshot,
        existing_violations: list[Violation],
    ) -> EngineRunResult:
        if not existing_violations:
            return actual_run_engine(snapshot, existing_violations)
        return EngineRunResult(
            violations=existing_violations,
            new_count=0,
            resolved_count=0,
            suppressed_rejected_count=0,
            preserved_count=len(existing_violations),
        )

    monkeypatch.setattr("eqm.ctadmin.service.run_engine", preserve_target)

    with pytest.raises(RepairDidNotClearError) as error:
        await execute_repair(
            store,
            finding.id,
            "demo-admin",
            {
                "pbl_description": (
                    "Provides read-only access to Ledger API for operations reporting."
                )
            },
        )

    assert error.value.violation.rule_id == "ENT-Q-01"
    assert _file_bytes(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [WorkflowState.PENDING_APPROVAL, WorkflowState.APPROVED, WorkflowState.MANUAL_REPAIR],
)
async def test_active_workflow_states_can_be_repaired(
    tmp_path: Path,
    state: WorkflowState,
) -> None:
    store, violations = await _seed_store(tmp_path, _bundle())
    finding = _finding(violations, "ENT-Q-01", "ENT-1")
    finding.workflow_state = state
    await _replace_violations(store, violations)

    receipt = await execute_repair(
        store,
        finding.id,
        "demo-admin",
        {
            "pbl_description": (
                "Provides read-only access to Ledger API for operations reporting."
            )
        },
    )

    assert receipt.workflow_state == WorkflowState.RESOLVED


@pytest.mark.asyncio
async def test_assignment_revocation_is_executed_and_verified(tmp_path: Path) -> None:
    current = _bundle(
        employees=[
            _employee(status=EmployeeStatus.TERMINATED, terminated_at=NOW)
        ],
        assignments=[_assignment()],
    )
    store, violations = await _seed_store(tmp_path, current)
    finding = _finding(violations, "HR-04", "ASN-1")

    receipt = await execute_repair(store, finding.id, "demo-admin", {})

    assignments = await store.read("assignments.json")
    assert isinstance(assignments, list)
    assert assignments[0]["active"] is False
    assert receipt.record_ids == ("ASN-1",)
    assert receipt.changes[0]["before"] == {"active": True}
    assert receipt.changes[0]["after"] == {"active": False}


@pytest.mark.asyncio
async def test_toxic_repair_can_revoke_multiple_assignments(tmp_path: Path) -> None:
    current = _bundle(
        entitlements=[
            _entitlement(
                id="ENT-L",
                pbl_description="Provides read-only access for payment initiation.",
                sod_tags=["payment_initiate"],
                linked_resource_ids=["RES-1"],
            ),
            _entitlement(
                id="ENT-R",
                pbl_description="Provides read-only access for payment approval.",
                sod_tags=["payment_approve"],
                linked_resource_ids=["RES-1"],
            ),
        ],
        assignments=[
            _assignment(id="ASN-L1", entitlement_id="ENT-L"),
            _assignment(id="ASN-L2", entitlement_id="ENT-L"),
            _assignment(id="ASN-R", entitlement_id="ENT-R"),
        ],
    )
    store, violations = await _seed_store(tmp_path, current)
    finding = _finding(violations, "TOX-01", "EMP-1")

    receipt = await execute_repair(store, finding.id, "demo-admin", {"side": "left"})

    assignments = await store.read("assignments.json")
    assert isinstance(assignments, list)
    active = {item["id"]: item["active"] for item in assignments}
    assert active == {"ASN-L1": False, "ASN-L2": False, "ASN-R": True}
    assert receipt.record_ids == ("ASN-L1", "ASN-L2")


@pytest.mark.asyncio
async def test_cmdb_repair_persists_reciprocal_links(tmp_path: Path) -> None:
    current = _bundle(
        entitlements=[
            _entitlement(
                pbl_description="Provides read-only access for operations reporting.",
                linked_resource_ids=[],
            )
        ],
        resources=[_resource(linked_entitlement_ids=[])],
    )
    store, violations = await _seed_store(tmp_path, current)
    finding = _finding(violations, "CMDB-01", "ENT-1")

    receipt = await execute_repair(
        store,
        finding.id,
        "demo-admin",
        {"resource_id": "RES-1"},
    )

    entitlements = await store.read("entitlements.json")
    resources = await store.read("cmdb_resources.json")
    assert isinstance(entitlements, list)
    assert isinstance(resources, list)
    assert entitlements[0]["linked_resource_ids"] == ["RES-1"]
    assert resources[0]["linked_entitlement_ids"] == ["ENT-1"]
    assert receipt.record_ids == ("ENT-1", "RES-1")


@pytest.mark.asyncio
async def test_tox03_constrained_choice_clears_three_division_footprint(
    tmp_path: Path,
) -> None:
    current = _bundle(
        entitlements=[
            _entitlement(
                id="ENT-1",
                pbl_description="Administrator access for finance operations.",
                access_tier=AccessTier.ADMIN,
                division=Division.FINANCE,
            ),
            _entitlement(
                id="ENT-2",
                pbl_description="Administrator access for human resources operations.",
                access_tier=AccessTier.ADMIN,
                division=Division.HR,
            ),
            _entitlement(
                id="ENT-3",
                pbl_description="Administrator access for compliance operations.",
                access_tier=AccessTier.ADMIN,
                division=Division.LEGAL_COMPLIANCE,
            ),
        ],
        assignments=[
            _assignment(id="ASN-1", entitlement_id="ENT-1"),
            _assignment(id="ASN-2", entitlement_id="ENT-2"),
            _assignment(id="ASN-3", entitlement_id="ENT-3"),
        ],
    )
    store, violations = await _seed_store(tmp_path, current)
    finding = _finding(violations, "TOX-03", "EMP-1")

    receipt = await execute_repair(
        store,
        finding.id,
        "demo-admin",
        {"assignment_ids": ["ASN-3"]},
    )

    assignments = await store.read("assignments.json")
    assert isinstance(assignments, list)
    active = {item["id"]: item["active"] for item in assignments}
    assert active == {"ASN-1": True, "ASN-2": True, "ASN-3": False}
    assert receipt.rule_id == "TOX-03"
