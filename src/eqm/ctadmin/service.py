"""Serialized, verified execution of CTADMIN finding repairs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from eqm.ctadmin.repairs import RepairPlan, apply_plan, build_repair_plan
from eqm.engine import run_engine
from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    Violation,
    WorkflowState,
)
from eqm.persistence import JsonStore
from eqm.rules.base import DataSnapshot
from eqm.seed import SeedBundle
from eqm.workflow import transition

_REPAIR_LOCK = asyncio.Lock()
_DATA_FILES = (
    "entitlements.json",
    "hr_employees.json",
    "cmdb_resources.json",
    "assignments.json",
    "violations.json",
)


class StaleFindingError(LookupError):
    """Raised when a finding can no longer be safely repaired."""


class RepairDidNotClearError(RuntimeError):
    """Raised when evaluation says the repaired condition remains active."""

    def __init__(self, violation: Violation) -> None:
        super().__init__(
            f"Repair did not clear {violation.rule_id} for "
            f"{violation.target_type}/{violation.target_id}."
        )
        self.violation = violation


@dataclass(frozen=True, slots=True)
class RepairReceipt:
    """A persisted, engine-verified repair result."""

    violation_id: str
    rule_id: str
    target_type: str
    target_id: str
    cleared: bool
    summary: str
    choice: dict[str, object]
    record_ids: tuple[str, ...]
    changes: tuple[dict[str, object], ...]
    workflow_state: WorkflowState


async def _read_list(store: JsonStore, name: str) -> list[dict[str, Any]]:
    raw = await store.read(name)
    if not isinstance(raw, list):
        raise ValueError(f"{name} must contain a JSON array.")
    return raw


async def _load_current(
    store: JsonStore,
) -> tuple[SeedBundle, list[Violation]]:
    entitlements, employees, resources, assignments, violations = await asyncio.gather(
        _read_list(store, "entitlements.json"),
        _read_list(store, "hr_employees.json"),
        _read_list(store, "cmdb_resources.json"),
        _read_list(store, "assignments.json"),
        _read_list(store, "violations.json"),
    )
    return (
        SeedBundle(
            entitlements=[Entitlement(**item) for item in entitlements],
            hr_employees=[HREmployee(**item) for item in employees],
            cmdb_resources=[CMDBResource(**item) for item in resources],
            assignments=[Assignment(**item) for item in assignments],
        ),
        [Violation(**item) for item in violations],
    )


def _prepare_workflow(violation: Violation, actor: str) -> None:
    state = violation.workflow_state
    if state in {WorkflowState.RESOLVED, WorkflowState.REJECTED}:
        raise StaleFindingError(
            f"Finding {violation.id} is already {state.value} and cannot be repaired."
        )
    if state == WorkflowState.OPEN:
        transition(
            violation,
            to=WorkflowState.PENDING_APPROVAL,
            actor=actor,
            note="CTADMIN repair submitted for approval.",
        )
        state = violation.workflow_state
    if state == WorkflowState.PENDING_APPROVAL:
        transition(
            violation,
            to=WorkflowState.MANUAL_REPAIR,
            actor=actor,
            note="CTADMIN manual repair started.",
        )


def _records(bundle: SeedBundle, collection: str) -> list[Any]:
    attribute = {
        "entitlements": "entitlements",
        "employees": "hr_employees",
        "resources": "cmdb_resources",
        "assignments": "assignments",
    }[collection]
    return getattr(bundle, attribute)


def _change_audit(
    before: SeedBundle,
    after: SeedBundle,
    plan: RepairPlan,
) -> tuple[dict[str, object], ...]:
    changes: list[dict[str, object]] = []
    for mutation in plan.mutations:
        old = next(item for item in _records(before, mutation.collection) if item.id == mutation.record_id)
        new = next(item for item in _records(after, mutation.collection) if item.id == mutation.record_id)
        old_values = old.model_dump(mode="json")
        new_values = new.model_dump(mode="json")
        fields = mutation.changes.keys()
        changes.append(
            {
                "collection": mutation.collection,
                "record_id": mutation.record_id,
                "before": {field: old_values[field] for field in fields},
                "after": {field: new_values[field] for field in fields},
            }
        )
    return tuple(changes)


def _active_target(
    violations: list[Violation],
    key: tuple[str, str, str],
) -> Violation | None:
    return next(
        (
            item
            for item in violations
            if (item.rule_id, item.target_type, item.target_id) == key
            and item.workflow_state
            not in {WorkflowState.RESOLVED, WorkflowState.REJECTED}
        ),
        None,
    )


def _current_finding(bundle: SeedBundle, violation: Violation) -> Violation:
    """Re-evaluate source data so stale state is distinct from bad user input."""
    key = (violation.rule_id, violation.target_type, violation.target_id)
    current = run_engine(
        DataSnapshot(
            bundle.entitlements,
            bundle.hr_employees,
            bundle.cmdb_resources,
            bundle.assignments,
        ),
        existing_violations=[],
    )
    detected = next(
        (
            item
            for item in current.violations
            if (item.rule_id, item.target_type, item.target_id) == key
        ),
        None,
    )
    if detected is None:
        raise StaleFindingError(
            f"Finding {violation.id} is stale and is not present in current source data."
        )
    if detected.evidence != violation.evidence:
        raise StaleFindingError(f"Finding {violation.id} evidence is stale.")
    return detected


def _resolved_target(
    violations: list[Violation],
    key: tuple[str, str, str],
) -> Violation:
    resolved = next(
        (
            item
            for item in violations
            if (item.rule_id, item.target_type, item.target_id) == key
            and item.workflow_state == WorkflowState.RESOLVED
        ),
        None,
    )
    if resolved is None:
        raise RuntimeError("The engine cleared a finding without a resolution record.")
    return resolved


def _enrich_resolution(
    violation: Violation,
    actor: str,
    plan: RepairPlan,
    changes: tuple[dict[str, object], ...],
) -> None:
    resolution = next(
        (
            entry
            for entry in reversed(violation.workflow_history)
            if entry.to_state == WorkflowState.RESOLVED
        ),
        None,
    )
    if resolution is None:
        raise RuntimeError("The engine did not create resolution history.")
    resolution.actor = actor
    resolution.note = f"CTADMIN repair verified: {plan.summary}"
    resolution.override_fix = {
        "source": "ctadmin",
        "actor": actor,
        "summary": plan.summary,
        "choice": deepcopy(plan.choice),
        "record_ids": [mutation.record_id for mutation in plan.mutations],
        "changes": [deepcopy(change) for change in changes],
        "cleared": True,
    }


def _documents(bundle: SeedBundle, violations: list[Violation]) -> dict[str, list[dict]]:
    return {
        "entitlements.json": [item.model_dump(mode="json") for item in bundle.entitlements],
        "hr_employees.json": [item.model_dump(mode="json") for item in bundle.hr_employees],
        "cmdb_resources.json": [
            item.model_dump(mode="json") for item in bundle.cmdb_resources
        ],
        "assignments.json": [item.model_dump(mode="json") for item in bundle.assignments],
        "violations.json": [item.model_dump(mode="json") for item in violations],
    }


async def execute_repair(
    store: JsonStore,
    violation_id: str,
    actor: str,
    submission: dict[str, object],
) -> RepairReceipt:
    """Validate, evaluate, audit, and atomically persist one repair."""
    if not actor.strip():
        raise ValueError("Repair actor is required.")

    async with _REPAIR_LOCK:
        for name in _DATA_FILES:
            store.invalidate(name)
        bundle, violations = await _load_current(store)
        matching = [item for item in violations if item.id == violation_id]
        if len(matching) != 1:
            raise StaleFindingError(f"Finding {violation_id} is missing or ambiguous.")
        violation = matching[0]
        if violation.workflow_state in {WorkflowState.RESOLVED, WorkflowState.REJECTED}:
            raise StaleFindingError(
                f"Finding {violation.id} is already {violation.workflow_state.value} "
                "and cannot be repaired."
            )
        _current_finding(bundle, violation)
        _prepare_workflow(violation, actor)

        plan = build_repair_plan(violation, bundle, submission)
        candidate = apply_plan(bundle, plan)
        changes = _change_audit(bundle, candidate, plan)
        key = (violation.rule_id, violation.target_type, violation.target_id)
        result = run_engine(
            DataSnapshot(
                candidate.entitlements,
                candidate.hr_employees,
                candidate.cmdb_resources,
                candidate.assignments,
            ),
            existing_violations=violations,
        )
        remaining = _active_target(result.violations, key)
        if remaining is not None:
            raise RepairDidNotClearError(remaining)

        resolved = _resolved_target(result.violations, key)
        _enrich_resolution(resolved, actor, plan, changes)
        await store.write_many(_documents(candidate, result.violations))

        return RepairReceipt(
            violation_id=violation.id,
            rule_id=violation.rule_id,
            target_type=violation.target_type,
            target_id=violation.target_id,
            cleared=True,
            summary=plan.summary,
            choice=deepcopy(plan.choice),
            record_ids=tuple(mutation.record_id for mutation in plan.mutations),
            changes=changes,
            workflow_state=resolved.workflow_state,
        )
