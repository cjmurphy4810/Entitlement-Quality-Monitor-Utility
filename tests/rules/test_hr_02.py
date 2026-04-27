from eqm.models import Division, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_02
from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_02_division_mismatch_fires():
    e = make_entitlement(id="ENT-1", division=Division.FINANCE,
                         acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_division=Division.HR,
                        current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    violations = HR_02.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].target_id == "ASN-1"
    assert violations[0].severity == "medium"


def test_hr_02_same_division_passes():
    e = make_entitlement(division=Division.HR)
    emp = make_employee(current_division=Division.HR)
    a = make_assignment()
    assert HR_02.evaluate(DataSnapshot([e], [emp], [], [a])) == []
