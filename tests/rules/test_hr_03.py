from datetime import timedelta

from eqm.models import Division, Role, RoleHistoryEntry
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_03
from tests.rules.conftest import NOW, make_assignment, make_employee, make_entitlement


def _emp_with_role_change(days_ago: int):
    return make_employee(
        id="EMP-1",
        current_role=Role.OPERATIONS,
        current_division=Division.TECH_OPS,
        role_history=[
            RoleHistoryEntry(role=Role.DEVELOPER, division=Division.TECH_DEV,
                             started_at=NOW - timedelta(days=400),
                             ended_at=NOW - timedelta(days=days_ago)),
            RoleHistoryEntry(role=Role.OPERATIONS, division=Division.TECH_OPS,
                             started_at=NOW - timedelta(days=days_ago), ended_at=None),
        ],
    )


def test_hr_03_role_change_31d_with_legacy_entitlement_fires():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=31)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1",
                        granted_at=NOW - timedelta(days=200))
    violations = HR_03.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].severity == "high"
    assert violations[0].target_id == "ASN-1"


def test_hr_03_role_change_29d_does_not_fire():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=29)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_03_no_role_change_history_does_not_fire():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_03_assignment_after_role_change_does_not_fire():
    # Granted AFTER the role change — that's intentional, not legacy.
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=60)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1",
                        granted_at=NOW - timedelta(days=10))  # post-change
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []
