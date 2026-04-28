from eqm.models import Role
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_01
from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_01_role_not_in_acceptable_fires():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.CUSTOMER)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    snap = DataSnapshot([e], [emp], [], [a])
    violations = HR_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_type == "assignment"
    assert violations[0].target_id == "ASN-1"
    assert violations[0].severity == "medium"
    assert violations[0].suggested_fix == {"_action": "delete_assignment"}


def test_hr_01_role_in_acceptable_passes():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS, Role.DEVELOPER])
    emp = make_employee(id="EMP-1", current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_01.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_01_inactive_assignment_ignored():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.CUSTOMER)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1", active=False)
    assert HR_01.evaluate(DataSnapshot([e], [emp], [], [a])) == []
