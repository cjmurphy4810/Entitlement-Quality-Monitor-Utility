from eqm.models import EmployeeStatus
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_04
from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_04_terminated_with_active_assignment_fires():
    e = make_entitlement(id="ENT-1")
    emp = make_employee(id="EMP-1", status=EmployeeStatus.TERMINATED)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    violations = HR_04.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].severity == "critical"
    assert violations[0].target_id == "ASN-1"


def test_hr_04_active_employee_passes():
    e = make_entitlement()
    emp = make_employee()
    a = make_assignment()
    assert HR_04.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_04_terminated_with_inactive_assignment_passes():
    e = make_entitlement()
    emp = make_employee(status=EmployeeStatus.TERMINATED)
    a = make_assignment(active=False)
    assert HR_04.evaluate(DataSnapshot([e], [emp], [], [a])) == []
