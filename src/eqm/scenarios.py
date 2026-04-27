"""Named demo scenarios that inject specific, deterministic violation sets."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from eqm.models import (
    AccessTier,
    Assignment,
    Division,
    EmployeeStatus,
    Entitlement,
    HREmployee,
    Role,
    RoleHistoryEntry,
)
from eqm.seed import SeedBundle


def _now() -> datetime:
    return datetime.now(UTC)


def _next_id(prefix: str, items) -> str:
    nums = [int(i.id.split("-")[1]) for i in items if i.id.startswith(prefix)]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:05d}"


def _scenario_terminated_user_with_admin(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Bob Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.TERMINATED,
        role_history=[RoleHistoryEntry(role=Role.OPERATIONS,
                                       division=Division.TECH_OPS,
                                       started_at=now - timedelta(days=400), ended_at=None)],
        manager_id=None,
        hired_at=now - timedelta(days=400),
        terminated_at=now - timedelta(days=1),
    )
    b.hr_employees.append(emp)
    ent = next((e for e in b.entitlements
                if e.access_tier == AccessTier.ADMIN), b.entitlements[0])
    b.assignments.append(Assignment(
        id=_next_id("ASN", b.assignments),
        employee_id=emp.id, entitlement_id=ent.id,
        granted_at=now - timedelta(days=200), granted_by="system",
        last_certified_at=None, active=True,
    ))


def _scenario_sod_payment_breach(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Eve Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.BUSINESS_USER, current_division=Division.FINANCE,
        status=EmployeeStatus.ACTIVE,
        role_history=[RoleHistoryEntry(role=Role.BUSINESS_USER,
                                       division=Division.FINANCE,
                                       started_at=now - timedelta(days=200), ended_at=None)],
        manager_id=None, hired_at=now - timedelta(days=200), terminated_at=None,
    )
    b.hr_employees.append(emp)
    e_init = Entitlement(
        id=_next_id("ENT", b.entitlements), name="Payments — Initiate",
        pbl_description="Allows users to initiate payment requests in the treasury system.",
        access_tier=AccessTier.READ_WRITE,
        acceptable_roles=[Role.BUSINESS_USER, Role.BUSINESS_ANALYST],
        division=Division.FINANCE,
        linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
        sod_tags=["payment_initiate"], created_at=now, updated_at=now,
    )
    e_appr = Entitlement(
        id=_next_id("ENT", b.entitlements + [e_init]), name="Payments — Approve",
        pbl_description="Allows users to approve initiated payment requests in the treasury system.",
        access_tier=AccessTier.READ_WRITE,
        acceptable_roles=[Role.BUSINESS_USER, Role.BUSINESS_ANALYST],
        division=Division.FINANCE,
        linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
        sod_tags=["payment_approve"], created_at=now, updated_at=now,
    )
    b.entitlements.extend([e_init, e_appr])
    for ent in (e_init, e_appr):
        b.assignments.append(Assignment(
            id=_next_id("ASN", b.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now - timedelta(days=30), granted_by="system",
            last_certified_at=None, active=True,
        ))


def _scenario_legacy_entitlements_after_promotion(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Carol Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.ACTIVE,
        role_history=[
            RoleHistoryEntry(role=Role.DEVELOPER, division=Division.TECH_DEV,
                             started_at=now - timedelta(days=300),
                             ended_at=now - timedelta(days=45)),
            RoleHistoryEntry(role=Role.OPERATIONS, division=Division.TECH_OPS,
                             started_at=now - timedelta(days=45), ended_at=None),
        ],
        manager_id=None, hired_at=now - timedelta(days=300), terminated_at=None,
    )
    b.hr_employees.append(emp)
    # Find existing dev-only entitlements; if fewer than 3 exist, create the missing ones.
    dev_only_existing = [e for e in b.entitlements
                          if Role.DEVELOPER in e.acceptable_roles
                          and Role.OPERATIONS not in e.acceptable_roles]
    needed = 3 - len(dev_only_existing[:3])
    new_dev_ents: list[Entitlement] = []
    for i in range(needed):
        new_dev_ents.append(Entitlement(
            id=_next_id("ENT", b.entitlements + new_dev_ents),
            name=f"Dev tooling {i}",
            pbl_description="Provides developer access to the engineering build system for code commits.",
            access_tier=AccessTier.READ_WRITE,
            acceptable_roles=[Role.DEVELOPER],
            division=Division.TECH_DEV,
            linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
            sod_tags=[], created_at=now - timedelta(days=200),
            updated_at=now - timedelta(days=200),
        ))
    b.entitlements.extend(new_dev_ents)
    target_ents = (dev_only_existing[:3] + new_dev_ents)[:3]
    for ent in target_ents:
        b.assignments.append(Assignment(
            id=_next_id("ASN", b.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now - timedelta(days=200), granted_by="system",
            last_certified_at=None, active=True,
        ))


def _scenario_bad_pbl_batch(b: SeedBundle) -> None:
    now = _now()
    bad_descriptions = ["x", "stuff", "do things", "x", "y",
                        "Provides users with access for reporting purposes.",  # tier-4 missing 'read-only'
                        "Manages production system."]                         # tier-1 missing 'administrator'
    tiers = [AccessTier.READ_WRITE, AccessTier.READ_WRITE, AccessTier.READ_WRITE,
             AccessTier.READ_WRITE, AccessTier.READ_WRITE,
             AccessTier.GENERAL_RO, AccessTier.ADMIN]
    for i, (desc, tier) in enumerate(zip(bad_descriptions, tiers, strict=True)):
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name=f"bad-pbl-{i}", pbl_description=desc, access_tier=tier,
            acceptable_roles=[Role.OPERATIONS], division=Division.TECH_OPS,
            linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_tier_role_mismatch(b: SeedBundle) -> None:
    now = _now()
    for roles in [[Role.CUSTOMER], [Role.BUSINESS_USER]]:
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name="bad-tier1", pbl_description="Grants administrator access to the production system.",
            access_tier=AccessTier.ADMIN, acceptable_roles=roles,
            division=Division.FINANCE,
            linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_orphan_entitlements(b: SeedBundle) -> None:
    now = _now()
    for i in range(4):
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name=f"orphan-{i}",
            pbl_description="Provides standard authorized read access to a system for users.",
            access_tier=AccessTier.READ_WRITE,
            acceptable_roles=[Role.OPERATIONS], division=Division.TECH_OPS,
            linked_resource_ids=[],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_kitchen_sink(b: SeedBundle) -> None:
    for fn in (_scenario_terminated_user_with_admin,
               _scenario_sod_payment_breach,
               _scenario_legacy_entitlements_after_promotion,
               _scenario_bad_pbl_batch,
               _scenario_tier_role_mismatch,
               _scenario_orphan_entitlements):
        fn(b)


SCENARIOS: dict[str, Callable[[SeedBundle], None]] = {
    "terminated_user_with_admin": _scenario_terminated_user_with_admin,
    "sod_payment_breach": _scenario_sod_payment_breach,
    "legacy_entitlements_after_promotion": _scenario_legacy_entitlements_after_promotion,
    "bad_pbl_batch": _scenario_bad_pbl_batch,
    "tier_role_mismatch": _scenario_tier_role_mismatch,
    "orphan_entitlements": _scenario_orphan_entitlements,
    "kitchen_sink": _scenario_kitchen_sink,
}


def run_scenario(name: str, bundle: SeedBundle) -> None:
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {name}. Known: {sorted(SCENARIOS)}")
    SCENARIOS[name](bundle)
