from datetime import UTC, datetime

import pytest

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
from eqm.rules.base import DataSnapshot

NOW = datetime.now(UTC)


@pytest.fixture
def empty_snapshot() -> DataSnapshot:
    return DataSnapshot(entitlements=[], hr_employees=[], cmdb_resources=[],
                         assignments=[])


def make_entitlement(**kw) -> Entitlement:
    defaults = dict(
        id="ENT-1", name="Test Entitlement",
        pbl_description="Grants administrator access to the test system for managing configuration.",
        access_tier=AccessTier.ADMIN, acceptable_roles=[Role.OPERATIONS],
        division=Division.TECH_OPS, linked_resource_ids=["RES-1"],
        sod_tags=[], created_at=NOW, updated_at=NOW,
    )
    defaults.update(kw)
    return Entitlement(**defaults)


def make_employee(**kw) -> HREmployee:
    defaults = dict(
        id="EMP-1", full_name="Test User", email="test@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.ACTIVE,
        role_history=[RoleHistoryEntry(role=Role.OPERATIONS,
                                       division=Division.TECH_OPS,
                                       started_at=NOW, ended_at=None)],
        manager_id=None, hired_at=NOW, terminated_at=None,
    )
    defaults.update(kw)
    return HREmployee(**defaults)


def make_resource(**kw) -> CMDBResource:
    defaults = dict(
        id="RES-1", name="Test Resource", type=ResourceType.APPLICATION,
        criticality=Criticality.LOW, owner_division=Division.TECH_OPS,
        environment="prod", linked_entitlement_ids=[], description="x",
    )
    defaults.update(kw)
    return CMDBResource(**defaults)


def make_assignment(**kw) -> Assignment:
    defaults = dict(
        id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1",
        granted_at=NOW, granted_by="system", last_certified_at=None,
        active=True,
    )
    defaults.update(kw)
    return Assignment(**defaults)
