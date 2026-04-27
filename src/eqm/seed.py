"""Deterministic seed data generation using Faker."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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

NOW = datetime.now(UTC)
SOD_TAG_PAIRS = [("payment_initiate", "payment_approve"),
                 ("trade_initiate", "trade_settle")]


@dataclass(slots=True)
class SeedConfig:
    num_entitlements: int = 200
    num_employees: int = 500
    num_resources: int = 75
    num_assignments: int = 1200
    seed: int = 42


@dataclass(slots=True)
class SeedBundle:
    entitlements: list[Entitlement]
    hr_employees: list[HREmployee]
    cmdb_resources: list[CMDBResource]
    assignments: list[Assignment]


def _pbl_for(tier: AccessTier, system_name: str) -> str:
    if tier == AccessTier.ADMIN:
        return f"Grants administrator access and full configuration rights to the {system_name} system."
    if tier == AccessTier.READ_WRITE:
        return f"Allows authorized users to read and write business records in {system_name}."
    if tier == AccessTier.ELEVATED_RO:
        return f"Provides elevated read access in {system_name} with limited write capability for approved exceptions."
    return f"Provides general read-only visibility into {system_name} for reporting and review purposes."


def generate_seed(cfg: SeedConfig) -> SeedBundle:
    rnd = random.Random(cfg.seed)
    fake = Faker()
    Faker.seed(cfg.seed)

    resources: list[CMDBResource] = []
    for i in range(cfg.num_resources):
        rt = rnd.choice(list(ResourceType))
        resources.append(CMDBResource(
            id=f"RES-{i+1:05d}",
            name=fake.unique.company() + " " + rt.value.capitalize(),
            type=rt,
            criticality=rnd.choice(list(Criticality)),
            owner_division=rnd.choice(list(Division)),
            environment=rnd.choice(["dev", "staging", "prod"]),
            linked_entitlement_ids=[],
            description=fake.sentence(),
        ))

    entitlements: list[Entitlement] = []
    for i in range(cfg.num_entitlements):
        tier = rnd.choice(list(AccessTier))
        division = rnd.choice(list(Division))
        # Roles allowed at each tier — keep ENT-Q-03 clean for seed data
        if tier == AccessTier.ADMIN:
            allowed = [Role.DEVELOPER, Role.OPERATIONS]
        elif tier == AccessTier.READ_WRITE:
            allowed = [Role.DEVELOPER, Role.OPERATIONS, Role.BUSINESS_ANALYST, Role.BUSINESS_USER]
        else:
            allowed = list(Role)
        roles = rnd.sample(allowed, k=rnd.randint(1, len(allowed)))
        linked = rnd.sample([r.id for r in resources], k=rnd.randint(1, min(3, len(resources))))
        sod = []
        if rnd.random() < 0.05:
            sod.append(rnd.choice([t for pair in SOD_TAG_PAIRS for t in pair]))
        system_name = resources[i % len(resources)].name
        e = Entitlement(
            id=f"ENT-{i+1:05d}",
            name=f"{division.value} {tier.name.lower()} {i+1}",
            pbl_description=_pbl_for(tier, system_name),
            access_tier=tier,
            acceptable_roles=roles,
            division=division,
            linked_resource_ids=linked,
            sod_tags=sod,
            created_at=NOW - timedelta(days=rnd.randint(0, 365)),
            updated_at=NOW,
        )
        entitlements.append(e)
        for rid in linked:
            res = next(r for r in resources if r.id == rid)
            res.linked_entitlement_ids.append(e.id)

    employees: list[HREmployee] = []
    for i in range(cfg.num_employees):
        role = rnd.choice(list(Role))
        division = rnd.choice(list(Division))
        hired_days_ago = rnd.randint(30, 1500)
        hired_at = NOW - timedelta(days=hired_days_ago)
        status = rnd.choices(
            list(EmployeeStatus), weights=[0.92, 0.05, 0.03], k=1)[0]
        history = [RoleHistoryEntry(role=role, division=division,
                                    started_at=hired_at, ended_at=None)]
        terminated_at = NOW - timedelta(days=rnd.randint(1, 60)) if status == EmployeeStatus.TERMINATED else None
        employees.append(HREmployee(
            id=f"EMP-{i+1:05d}",
            full_name=fake.name(),
            email=f"user{i+1:05d}@example.com",
            current_role=role,
            current_division=division,
            status=status,
            role_history=history,
            manager_id=None,
            hired_at=hired_at,
            terminated_at=terminated_at,
        ))

    assignments: list[Assignment] = []
    for i in range(cfg.num_assignments):
        emp = rnd.choice(employees)
        ent = rnd.choice(entitlements)
        assignments.append(Assignment(
            id=f"ASN-{i+1:05d}",
            employee_id=emp.id,
            entitlement_id=ent.id,
            granted_at=NOW - timedelta(days=rnd.randint(0, 365)),
            granted_by="system",
            last_certified_at=NOW - timedelta(days=rnd.randint(0, 180)) if rnd.random() < 0.6 else None,
            active=True,
        ))

    return SeedBundle(entitlements=entitlements, hr_employees=employees,
                      cmdb_resources=resources, assignments=assignments)
