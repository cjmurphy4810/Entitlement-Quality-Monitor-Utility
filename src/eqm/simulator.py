"""Drift-mode simulator: random, mostly-realistic mutations seeded by tick number."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from faker import Faker

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
    RoleHistoryEntry,
)
from eqm.seed import SeedBundle


def _now() -> datetime:
    return datetime.now(UTC)


BAD_PBL_PHRASES = ["This entitlement gives access stuff for users.",
                   "Lets the user do things in the system.",
                   "admin access for whoever needs it"]


@dataclass(slots=True)
class DriftSummary:
    tick_number: int
    new_employees: int = 0
    role_changes: int = 0
    terminations: int = 0
    new_assignments: int = 0
    new_certifications: int = 0
    new_entitlements: int = 0
    new_resources: int = 0
    tier_changes: int = 0
    changes: list[str] = field(default_factory=list)


def _next_id(prefix: str, items) -> str:
    nums = [int(i.id.split("-")[1]) for i in items if i.id.startswith(prefix)]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:05d}"


def drift_tick(bundle: SeedBundle, tick_number: int) -> DriftSummary:
    rnd = random.Random(tick_number * 1009 + 7)
    fake = Faker()
    Faker.seed(tick_number)
    s = DriftSummary(tick_number=tick_number)
    now = _now()

    # New employees
    for _ in range(rnd.randint(0, 2)):
        eid = _next_id("EMP", bundle.hr_employees)
        role = rnd.choice(list(Role))
        division = rnd.choice(list(Division))
        bundle.hr_employees.append(HREmployee(
            id=eid, full_name=fake.name(),
            email=f"{eid.lower()}@example.com",
            current_role=role, current_division=division,
            status=EmployeeStatus.ACTIVE,
            role_history=[RoleHistoryEntry(role=role, division=division,
                                           started_at=now, ended_at=None)],
            manager_id=None, hired_at=now, terminated_at=None,
        ))
        s.new_employees += 1
        s.changes.append(f"new employee {eid}")

    # Role change (creates legacy seed for HR-03)
    if rnd.random() < 0.5 and bundle.hr_employees:
        emp = rnd.choice(bundle.hr_employees)
        if emp.status == EmployeeStatus.ACTIVE and emp.role_history[-1].ended_at is None:
            emp.role_history[-1] = RoleHistoryEntry(
                role=emp.role_history[-1].role,
                division=emp.role_history[-1].division,
                started_at=emp.role_history[-1].started_at,
                ended_at=now,
            )
            new_role = rnd.choice([r for r in Role if r != emp.current_role])
            new_div = rnd.choice([d for d in Division if d != emp.current_division])
            emp.role_history.append(RoleHistoryEntry(
                role=new_role, division=new_div, started_at=now, ended_at=None))
            emp.current_role = new_role
            emp.current_division = new_div
            s.role_changes += 1
            s.changes.append(f"role change {emp.id}")

    # Termination (seeds HR-04)
    if rnd.random() < 0.3 and bundle.hr_employees:
        active = [e for e in bundle.hr_employees if e.status == EmployeeStatus.ACTIVE]
        if active:
            emp = rnd.choice(active)
            emp.status = EmployeeStatus.TERMINATED
            emp.terminated_at = now
            s.terminations += 1
            s.changes.append(f"terminated {emp.id}")

    # New assignments
    for _ in range(rnd.randint(1, 3)):
        if not bundle.hr_employees or not bundle.entitlements:
            break
        emp = rnd.choice(bundle.hr_employees)
        ent = rnd.choice(bundle.entitlements)
        bundle.assignments.append(Assignment(
            id=_next_id("ASN", bundle.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now, granted_by="system",
            last_certified_at=None, active=True,
        ))
        s.new_assignments += 1

    # Certifications
    for _ in range(rnd.randint(0, 5)):
        if not bundle.assignments:
            break
        a = rnd.choice(bundle.assignments)
        a.last_certified_at = now
        s.new_certifications += 1

    # New entitlement (sometimes bad PBL)
    if rnd.random() < 0.3:
        eid = _next_id("ENT", bundle.entitlements)
        tier = rnd.choice(list(AccessTier))
        is_bad = rnd.random() < 0.4
        pbl = (rnd.choice(BAD_PBL_PHRASES) if is_bad
               else f"Provides {'administrator' if tier == AccessTier.ADMIN else 'read-only' if tier == AccessTier.GENERAL_RO else 'standard'} "
                    f"access to a system for authorized users.")
        bundle.entitlements.append(Entitlement(
            id=eid, name=f"new entitlement {eid}",
            pbl_description=pbl,
            access_tier=tier,
            acceptable_roles=[rnd.choice(list(Role))],
            division=rnd.choice(list(Division)),
            linked_resource_ids=([rnd.choice(bundle.cmdb_resources).id]
                                 if bundle.cmdb_resources and rnd.random() < 0.7 else []),
            sod_tags=[], created_at=now, updated_at=now,
        ))
        s.new_entitlements += 1
        s.changes.append(f"new entitlement {eid} ({'bad' if is_bad else 'clean'})")

    # New resource (sometimes orphan)
    if rnd.random() < 0.2:
        rid = _next_id("RES", bundle.cmdb_resources)
        bundle.cmdb_resources.append(CMDBResource(
            id=rid, name=fake.company(), type=rnd.choice(list(ResourceType)),
            criticality=rnd.choice(list(Criticality)),
            owner_division=rnd.choice(list(Division)),
            environment=rnd.choice(["dev", "staging", "prod"]),
            linked_entitlement_ids=[], description=fake.sentence(),
        ))
        s.new_resources += 1

    # Tier change
    if rnd.random() < 0.1 and bundle.entitlements:
        ent = rnd.choice(bundle.entitlements)
        ent.access_tier = rnd.choice(list(AccessTier))
        ent.updated_at = now
        s.tier_changes += 1

    return s
