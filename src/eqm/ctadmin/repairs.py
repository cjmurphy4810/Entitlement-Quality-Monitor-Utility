"""Pure mutation planning for CTAdmin violation repairs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from eqm.models import (
    AccessTier,
    Assignment,
    Criticality,
    Division,
    EmployeeStatus,
    Entitlement,
    Role,
    Violation,
)
from eqm.rules.base import now_utc
from eqm.rules.entitlement_quality import BANNED_PHRASES
from eqm.rules.hr_coherence import LEGACY_DAYS_THRESHOLD
from eqm.rules.toxic_combinations import SOD_PAIRS
from eqm.seed import SeedBundle

CollectionName = Literal["entitlements", "employees", "resources", "assignments"]
RepairBuilder = Callable[[Violation, SeedBundle, dict[str, object]], "RepairPlan"]


class RepairValidationError(ValueError):
    """Raised when a repair choice is invalid for the current finding state."""


@dataclass(frozen=True, slots=True)
class RecordMutation:
    collection: CollectionName
    record_id: str
    changes: dict[str, object]


@dataclass(frozen=True, slots=True)
class RepairPlan:
    violation_key: tuple[str, str, str]
    rule_id: str
    summary: str
    choice: dict[str, object]
    mutations: tuple[RecordMutation, ...]


def _plan(
    violation: Violation,
    submission: dict[str, object],
    summary: str,
    *mutations: RecordMutation,
) -> RepairPlan:
    if not mutations:
        raise RepairValidationError("The proposed repair would not change current state.")
    return RepairPlan(
        violation_key=(violation.id, violation.rule_id, violation.target_id),
        rule_id=violation.rule_id,
        summary=summary,
        choice=dict(submission),
        mutations=tuple(mutations),
    )


def _require_target(violation: Violation, expected_type: str) -> None:
    if violation.target_type != expected_type:
        raise RepairValidationError(
            f"Rule {violation.rule_id} requires a {expected_type} target."
        )


def _find(items: list[object], record_id: str, kind: str) -> object:
    item = next((candidate for candidate in items if candidate.id == record_id), None)
    if item is None:
        raise RepairValidationError(f"The {kind} {record_id} is missing or stale.")
    return item


def _entitlement(violation: Violation, bundle: SeedBundle) -> Entitlement:
    _require_target(violation, "entitlement")
    return _find(bundle.entitlements, violation.target_id, "entitlement")  # type: ignore[return-value]


def _assignment(violation: Violation, bundle: SeedBundle) -> Assignment:
    _require_target(violation, "assignment")
    item = _find(bundle.assignments, violation.target_id, "assignment")
    if not isinstance(item, Assignment):
        raise RepairValidationError("The assignment target is invalid.")
    if not item.active:
        raise RepairValidationError(f"Assignment {item.id} is inactive or stale.")
    return item


def _evidence(violation: Violation, key: str, expected: object) -> None:
    if key not in violation.evidence or violation.evidence[key] != expected:
        raise RepairValidationError(f"Finding evidence for {key} is stale.")


def _submission_keys(submission: dict[str, object], *keys: str) -> None:
    expected = set(keys)
    if set(submission) != expected:
        rendered = ", ".join(sorted(expected)) or "no fields"
        raise RepairValidationError(f"Repair submission must contain exactly {rendered}.")


def _pbl_text(submission: dict[str, object]) -> str:
    _submission_keys(submission, "pbl_description")
    value = submission["pbl_description"]
    if not isinstance(value, str):
        raise RepairValidationError("PBL description must be text.")
    text = value.strip()
    lowered = text.lower()
    placeholders = ("[owner", "please rewrite", "template", "placeholder")
    if not text or any(marker in lowered for marker in placeholders):
        raise RepairValidationError("PBL description cannot be blank or template placeholder text.")
    return text


def _roles(submission: dict[str, object], *, allow_empty: bool = False) -> list[str]:
    _submission_keys(submission, "acceptable_roles")
    raw = submission["acceptable_roles"]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RepairValidationError("acceptable_roles must be a list of roles.")
    if not raw and not allow_empty:
        raise RepairValidationError("acceptable_roles must be a non-empty list of roles.")
    try:
        result = [Role(item).value for item in raw]
    except ValueError as exc:
        raise RepairValidationError("acceptable_roles contains an unknown role.") from exc
    if len(result) != len(set(result)):
        raise RepairValidationError("acceptable_roles cannot contain duplicates.")
    return result


def _tier(submission: dict[str, object]) -> int:
    _submission_keys(submission, "access_tier")
    value = submission["access_tier"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RepairValidationError("access_tier must be an integer from 1 through 4.")
    try:
        return int(AccessTier(value))
    except ValueError as exc:
        raise RepairValidationError("access_tier must be an integer from 1 through 4.") from exc


def _build_ent_q_01(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    current_description = (ent.pbl_description or "").strip().lower()
    current_reasons: list[str] = []
    if len(current_description) < 20:
        current_reasons.append(f"length={len(current_description)} < 20")
    for phrase in BANNED_PHRASES:
        if phrase in current_description:
            current_reasons.append(f"banned phrase: '{phrase}'")
    _evidence(violation, "pbl_description", ent.pbl_description)
    _evidence(violation, "reasons", current_reasons)
    if not current_reasons:
        raise RepairValidationError("ENT-Q-01 is no longer present in current state.")
    text = _pbl_text(submission)
    lowered = text.lower()
    if len(lowered) < 20 or any(phrase in lowered for phrase in BANNED_PHRASES):
        raise RepairValidationError("PBL description does not clear ENT-Q-01.")
    if text == ent.pbl_description:
        raise RepairValidationError("PBL description is unchanged.")
    return _plan(
        violation,
        submission,
        f"Update the PBL description for entitlement {ent.id}.",
        RecordMutation("entitlements", ent.id, {"pbl_description": text}),
    )


def _build_ent_q_02(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    _evidence(violation, "access_tier", int(ent.access_tier))
    _evidence(violation, "pbl_description", ent.pbl_description)
    current_description = (ent.pbl_description or "").lower()
    currently_violates = (
        ent.access_tier == AccessTier.ADMIN
        and "administrator" not in current_description
    ) or (
        ent.access_tier == AccessTier.GENERAL_RO
        and "read-only" not in current_description
        and "read only" not in current_description
    )
    if not currently_violates:
        raise RepairValidationError("ENT-Q-02 is no longer present in current state.")
    text = _pbl_text(submission)
    lowered = text.lower()
    matches_tier = (
        ent.access_tier == AccessTier.ADMIN and "administrator" in lowered
    ) or (
        ent.access_tier == AccessTier.GENERAL_RO
        and ("read-only" in lowered or "read only" in lowered)
    )
    if not matches_tier:
        raise RepairValidationError("PBL description does not match the entitlement tier.")
    if text == ent.pbl_description:
        raise RepairValidationError("PBL description is unchanged.")
    return _plan(
        violation,
        submission,
        f"Update the PBL description for entitlement {ent.id}.",
        RecordMutation("entitlements", ent.id, {"pbl_description": text}),
    )


def _build_ent_q_03(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    current_roles = [role.value for role in ent.acceptable_roles]
    forbidden = [
        role for role in current_roles if role in {Role.CUSTOMER.value, Role.BUSINESS_USER.value}
    ]
    _evidence(violation, "access_tier", int(ent.access_tier))
    _evidence(violation, "acceptable_roles", current_roles)
    _evidence(violation, "forbidden_roles", forbidden)
    if ent.access_tier != AccessTier.ADMIN or not forbidden:
        raise RepairValidationError("ENT-Q-03 is no longer present in current state.")
    expected = [role for role in current_roles if role not in forbidden]
    proposed = _roles(submission, allow_empty=not expected)
    if proposed != expected:
        raise RepairValidationError(
            "ENT-Q-03 must remove exactly the evidence-identified forbidden roles."
        )
    return _plan(
        violation,
        submission,
        f"Update acceptable roles for entitlement {ent.id}.",
        RecordMutation("entitlements", ent.id, {"acceptable_roles": proposed}),
    )


def _build_ent_q_04(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    current_roles = [role.value for role in ent.acceptable_roles]
    _evidence(violation, "division", ent.division.value)
    _evidence(violation, "access_tier", int(ent.access_tier))
    _evidence(violation, "acceptable_roles", current_roles)
    if ent.division == Division.HR and Role.DEVELOPER in ent.acceptable_roles:
        expected = [role for role in current_roles if role != Role.DEVELOPER.value]
        proposed = _roles(submission, allow_empty=not expected)
        if proposed != expected:
            raise RepairValidationError("ENT-Q-04 must remove exactly the developer role.")
        return _plan(
            violation,
            submission,
            f"Remove incoherent roles from entitlement {ent.id}.",
            RecordMutation("entitlements", ent.id, {"acceptable_roles": proposed}),
        )

    resources = {item.id: item for item in bundle.cmdb_resources}
    prod_ids = [
        resource_id
        for resource_id in ent.linked_resource_ids
        if resource_id in resources and resources[resource_id].environment == "prod"
    ]
    if (
        ent.division != Division.LEGAL_COMPLIANCE
        or ent.access_tier != AccessTier.ADMIN
        or not prod_ids
    ):
        raise RepairValidationError("ENT-Q-04 is no longer present in current state.")
    _evidence(violation, "prod_resources", prod_ids)
    proposed_tier = _tier(submission)
    if proposed_tier != int(AccessTier.READ_WRITE):
        raise RepairValidationError("ENT-Q-04 repair must set access_tier to Tier-2.")
    return _plan(
        violation,
        submission,
        f"Reduce the access tier for entitlement {ent.id} to Tier-{proposed_tier}.",
        RecordMutation("entitlements", ent.id, {"access_tier": proposed_tier}),
    )


def _validate_assignment_evidence(
    violation: Violation, bundle: SeedBundle, item: Assignment
) -> None:
    employee = _find(bundle.hr_employees, item.employee_id, "employee")
    ent = _find(bundle.entitlements, item.entitlement_id, "entitlement")
    _evidence(violation, "employee_id", item.employee_id)
    if violation.rule_id == "HR-01":
        _evidence(violation, "employee_role", employee.current_role.value)
        _evidence(violation, "entitlement_id", item.entitlement_id)
        _evidence(
            violation,
            "acceptable_roles",
            [role.value for role in ent.acceptable_roles],
        )
        if employee.current_role in ent.acceptable_roles:
            raise RepairValidationError("HR-01 is no longer present in current state.")
    elif violation.rule_id == "HR-02":
        _evidence(violation, "employee_division", employee.current_division.value)
        _evidence(violation, "entitlement_id", item.entitlement_id)
        _evidence(violation, "entitlement_division", ent.division.value)
        if employee.current_division == ent.division:
            raise RepairValidationError("HR-02 is no longer present in current state.")
    elif violation.rule_id == "HR-03":
        _evidence(violation, "current_role", employee.current_role.value)
        ended = [entry for entry in employee.role_history if entry.ended_at is not None]
        if not ended:
            raise RepairValidationError("HR-03 role history is stale.")
        last_change = max(entry.ended_at for entry in ended)
        prior_roles = {entry.role.value for entry in ended}
        evidence_roles = violation.evidence.get("prior_roles")
        if not isinstance(evidence_roles, list) or set(evidence_roles) != prior_roles:
            raise RepairValidationError("Finding evidence for prior_roles is stale.")
        _evidence(violation, "last_role_change_at", last_change.isoformat())
        _evidence(violation, "granted_at", item.granted_at.isoformat())
        if (
            last_change > now_utc() - timedelta(days=LEGACY_DAYS_THRESHOLD)
            or item.granted_at >= last_change
            or employee.current_role in ent.acceptable_roles
            or not ({role.value for role in ent.acceptable_roles} & prior_roles)
        ):
            raise RepairValidationError("HR-03 is no longer present in current state.")
    elif violation.rule_id == "HR-04":
        terminated_at = employee.terminated_at.isoformat() if employee.terminated_at else None
        _evidence(violation, "terminated_at", terminated_at)
        _evidence(violation, "entitlement_id", item.entitlement_id)
        if employee.status != EmployeeStatus.TERMINATED:
            raise RepairValidationError("HR-04 is no longer present in current state.")


def _build_assignment_revocation(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    if violation.rule_id == "HR-03":
        _submission_keys(submission, "manager_confirmed")
        if submission["manager_confirmed"] is not True:
            raise RepairValidationError("Manager confirmation is required for HR-03.")
    else:
        _submission_keys(submission)
    item = _assignment(violation, bundle)
    _validate_assignment_evidence(violation, bundle, item)
    return _plan(
        violation,
        submission,
        f"Revoke assignment {item.id}.",
        RecordMutation("assignments", item.id, {"active": False}),
    )


def _employee_assignments(
    violation: Violation, bundle: SeedBundle
) -> tuple[dict[str, Entitlement], list[Assignment]]:
    _require_target(violation, "employee")
    _find(bundle.hr_employees, violation.target_id, "employee")
    entitlements = {item.id: item for item in bundle.entitlements}
    assignments = [
        item
        for item in bundle.assignments
        if item.active and item.employee_id == violation.target_id
    ]
    return entitlements, assignments


def _revocation_mutations(assignments: list[Assignment]) -> tuple[RecordMutation, ...]:
    if not assignments:
        raise RepairValidationError("The selected evidence side has no active assignments.")
    return tuple(
        RecordMutation("assignments", item.id, {"active": False})
        for item in sorted(assignments, key=lambda candidate: candidate.id)
    )


def _build_tox_01(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    _submission_keys(submission, "side")
    side = submission["side"]
    if side not in {"left", "right"}:
        raise RepairValidationError("TOX-01 side must be left or right.")
    entitlements, assignments = _employee_assignments(violation, bundle)
    pair = violation.evidence.get("sod_pair")
    evidence_ids = violation.evidence.get("entitlement_ids")
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not all(isinstance(tag, str) for tag in pair)
        or tuple(pair) not in SOD_PAIRS
        or not isinstance(evidence_ids, list)
        or not all(isinstance(item, str) for item in evidence_ids)
    ):
        raise RepairValidationError("TOX-01 evidence is malformed or stale.")
    current_ids = sorted(
        {
            item.entitlement_id
            for item in assignments
            if item.entitlement_id in entitlements and entitlements[item.entitlement_id].sod_tags
        }
    )
    if sorted(evidence_ids) != current_ids:
        raise RepairValidationError("TOX-01 entitlement evidence is stale.")
    current_tags = {
        tag
        for item in assignments
        if item.entitlement_id in entitlements
        for tag in entitlements[item.entitlement_id].sod_tags
    }
    if not set(pair) <= current_tags:
        raise RepairValidationError("TOX-01 is no longer present in current state.")
    selected_tag = pair[0 if side == "left" else 1]
    selected = [
        item
        for item in assignments
        if item.entitlement_id in evidence_ids
        and selected_tag in entitlements[item.entitlement_id].sod_tags
    ]
    selected_ids = {item.id for item in selected}
    remaining_tags = {
        tag
        for item in assignments
        if item.id not in selected_ids and item.entitlement_id in entitlements
        for tag in entitlements[item.entitlement_id].sod_tags
    }
    if set(pair) <= remaining_tags:
        raise RepairValidationError("Selected assignments cannot clear TOX-01.")
    mutations = _revocation_mutations(selected)
    return _plan(
        violation,
        submission,
        f"Revoke the {side} side of TOX-01 for employee {violation.target_id}.",
        *mutations,
    )


def _build_tox_02(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    _submission_keys(submission, "side")
    side = submission["side"]
    if side not in {"developer", "operations"}:
        raise RepairValidationError("TOX-02 side must be developer or operations.")
    entitlements, assignments = _employee_assignments(violation, bundle)
    resource_id = violation.evidence.get("resource_id")
    if not isinstance(resource_id, str):
        raise RepairValidationError("TOX-02 resource evidence is malformed or stale.")
    current_dev: set[str] = set()
    current_ops: set[str] = set()
    for item in assignments:
        ent = entitlements.get(item.entitlement_id)
        if (
            ent is None
            or ent.access_tier != AccessTier.ADMIN
            or resource_id not in ent.linked_resource_ids
        ):
            continue
        if Role.DEVELOPER in ent.acceptable_roles:
            current_dev.add(ent.id)
        if Role.OPERATIONS in ent.acceptable_roles:
            current_ops.add(ent.id)
    evidence_dev = violation.evidence.get("developer_admin_entitlements")
    evidence_ops = violation.evidence.get("operations_admin_entitlements")
    if (
        not isinstance(evidence_dev, list)
        or not isinstance(evidence_ops, list)
        or sorted(evidence_dev) != sorted(current_dev)
        or sorted(evidence_ops) != sorted(current_ops)
        or not current_dev
        or not current_ops
    ):
        raise RepairValidationError("TOX-02 entitlement evidence is stale.")
    selected_entitlements = current_dev if side == "developer" else current_ops
    selected = [item for item in assignments if item.entitlement_id in selected_entitlements]
    selected_ids = {item.id for item in selected}
    remaining_entitlements = {
        item.entitlement_id for item in assignments if item.id not in selected_ids
    }
    if current_dev & remaining_entitlements and current_ops & remaining_entitlements:
        raise RepairValidationError("Selected assignments cannot clear TOX-02.")
    mutations = _revocation_mutations(selected)
    return _plan(
        violation,
        submission,
        f"Revoke the {side} side of TOX-02 for employee {violation.target_id}.",
        *mutations,
    )


def _build_tox_03(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    _submission_keys(submission, "assignment_ids")
    raw_ids = submission["assignment_ids"]
    if (
        not isinstance(raw_ids, list)
        or not all(isinstance(item, str) for item in raw_ids)
        or len(raw_ids) != len(set(raw_ids))
    ):
        raise RepairValidationError("TOX-03 requires distinct assignment_ids.")
    entitlements, assignments = _employee_assignments(violation, bundle)
    tier_one = [
        item
        for item in assignments
        if item.entitlement_id in entitlements
        and entitlements[item.entitlement_id].access_tier == AccessTier.ADMIN
    ]
    current_entitlement_ids = sorted({item.entitlement_id for item in tier_one})
    current_divisions = sorted(
        {entitlements[item.entitlement_id].division.value for item in tier_one}
    )
    _evidence(violation, "entitlement_ids", current_entitlement_ids)
    _evidence(violation, "divisions", current_divisions)
    if len(current_divisions) < 3:
        raise RepairValidationError("TOX-03 is no longer present below three divisions.")
    eligible = {item.id: item for item in tier_one}
    if any(item_id not in eligible for item_id in raw_ids):
        raise RepairValidationError("TOX-03 selections must be evidence-derived assignments.")
    selected_ids = set(raw_ids)
    remaining_divisions = {
        entitlements[item.entitlement_id].division
        for item in tier_one
        if item.id not in selected_ids
    }
    if len(remaining_divisions) > 2:
        raise RepairValidationError(
            "TOX-03 repair must leave Tier-1 access in at most two divisions."
        )
    selected = [eligible[item_id] for item_id in raw_ids]
    mutations = _revocation_mutations(selected)
    count = len(mutations)
    noun = "assignment" if count == 1 else "assignments"
    return _plan(
        violation,
        submission,
        f"Revoke {count} Tier-1 {noun} for employee {violation.target_id}.",
        *mutations,
    )


def _build_cmdb_01(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    resources = {item.id: item for item in bundle.cmdb_resources}
    valid_links = [item for item in ent.linked_resource_ids if item in resources]
    _evidence(violation, "declared_links", ent.linked_resource_ids)
    _evidence(violation, "valid_links", valid_links)
    if valid_links:
        raise RepairValidationError("CMDB-01 is no longer present in current state.")
    _submission_keys(submission, "resource_id")
    resource_id = submission["resource_id"]
    if not isinstance(resource_id, str) or resource_id not in resources:
        raise RepairValidationError("A valid CMDB resource is required.")
    selected = resources[resource_id]
    ent_links = list(dict.fromkeys([*ent.linked_resource_ids, resource_id]))
    resource_links = list(dict.fromkeys([*selected.linked_entitlement_ids, ent.id]))
    mutations: list[RecordMutation] = []
    if ent_links != ent.linked_resource_ids:
        mutations.append(
            RecordMutation("entitlements", ent.id, {"linked_resource_ids": ent_links})
        )
    if resource_links != selected.linked_entitlement_ids:
        mutations.append(
            RecordMutation(
                "resources", selected.id, {"linked_entitlement_ids": resource_links}
            )
        )
    return _plan(
        violation,
        submission,
        f"Link entitlement {ent.id} to CMDB resource {selected.id}.",
        *mutations,
    )


def _build_cmdb_02(
    violation: Violation, bundle: SeedBundle, submission: dict[str, object]
) -> RepairPlan:
    ent = _entitlement(violation, bundle)
    resources = {item.id: item for item in bundle.cmdb_resources}
    offending = [
        {"id": item.id, "criticality": item.criticality.value}
        for resource_id in ent.linked_resource_ids
        if (item := resources.get(resource_id)) is not None
        and item.criticality in {Criticality.HIGH, Criticality.CRITICAL}
    ]
    _evidence(violation, "access_tier", int(ent.access_tier))
    _evidence(violation, "offending_resources", offending)
    if int(ent.access_tier) <= 2 or not offending:
        raise RepairValidationError("CMDB-02 is no longer present in current state.")
    proposed_tier = _tier(submission)
    if proposed_tier == int(ent.access_tier):
        raise RepairValidationError("access_tier is unchanged.")
    if proposed_tier != int(AccessTier.READ_WRITE):
        raise RepairValidationError("CMDB-02 repair must set access_tier to Tier-2.")
    return _plan(
        violation,
        submission,
        f"Reduce the access tier for entitlement {ent.id} to Tier-{proposed_tier}.",
        RecordMutation("entitlements", ent.id, {"access_tier": proposed_tier}),
    )


REPAIR_BUILDERS: dict[str, RepairBuilder] = {
    "ENT-Q-01": _build_ent_q_01,
    "ENT-Q-02": _build_ent_q_02,
    "ENT-Q-03": _build_ent_q_03,
    "ENT-Q-04": _build_ent_q_04,
    "TOX-01": _build_tox_01,
    "TOX-02": _build_tox_02,
    "TOX-03": _build_tox_03,
    "HR-01": _build_assignment_revocation,
    "HR-02": _build_assignment_revocation,
    "HR-03": _build_assignment_revocation,
    "HR-04": _build_assignment_revocation,
    "CMDB-01": _build_cmdb_01,
    "CMDB-02": _build_cmdb_02,
}


def build_repair_plan(
    violation: Violation,
    bundle: SeedBundle,
    submission: dict[str, object],
) -> RepairPlan:
    """Validate a submitted repair choice and describe its record mutations."""
    builder = REPAIR_BUILDERS.get(violation.rule_id)
    if builder is None:
        raise RepairValidationError(f"No repair planner exists for rule {violation.rule_id}.")
    return builder(violation, bundle, submission)


def apply_plan(bundle: SeedBundle, plan: RepairPlan) -> SeedBundle:
    """Apply a mutation plan to a deep copy of a seed bundle."""
    collection_attributes = {
        "entitlements": "entitlements",
        "employees": "hr_employees",
        "resources": "cmdb_resources",
        "assignments": "assignments",
    }
    copied = SeedBundle(
        entitlements=[item.model_copy(deep=True) for item in bundle.entitlements],
        hr_employees=[item.model_copy(deep=True) for item in bundle.hr_employees],
        cmdb_resources=[item.model_copy(deep=True) for item in bundle.cmdb_resources],
        assignments=[item.model_copy(deep=True) for item in bundle.assignments],
    )
    for mutation in plan.mutations:
        attribute = collection_attributes[mutation.collection]
        records = getattr(copied, attribute)
        index = next(
            (position for position, item in enumerate(records) if item.id == mutation.record_id),
            None,
        )
        if index is None:
            raise RepairValidationError(
                f"Plan target {mutation.collection}/{mutation.record_id} is missing."
            )
        current = records[index]
        unknown_fields = set(mutation.changes) - set(type(current).model_fields)
        if unknown_fields:
            raise RepairValidationError(
                f"Plan contains unknown fields for {mutation.collection}/{mutation.record_id}."
            )
        if all(getattr(current, key) == value for key, value in mutation.changes.items()):
            raise RepairValidationError(
                f"Plan would not change {mutation.collection}/{mutation.record_id}."
            )
        values = current.model_dump(mode="python")
        values.update(mutation.changes)
        records[index] = type(current).model_validate(values)
    return copied
