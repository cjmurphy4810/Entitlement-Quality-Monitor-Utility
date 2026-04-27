from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_01
from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_tox_01_user_holds_initiate_and_approve_fires():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    e2 = make_entitlement(id="ENT-2", sod_tags=["payment_approve"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-2")
    snap = DataSnapshot([e1, e2], [emp], [], [a1, a2])
    violations = TOX_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "critical"
    assert violations[0].target_id == "EMP-1"
    assert violations[0].target_type == "employee"


def test_tox_01_only_one_side_passes():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    snap = DataSnapshot([e1], [emp], [], [a1])
    assert TOX_01.evaluate(snap) == []


def test_tox_01_inactive_assignments_ignored():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    e2 = make_entitlement(id="ENT-2", sod_tags=["payment_approve"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1",
                         entitlement_id="ENT-1", active=False)
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-2")
    snap = DataSnapshot([e1, e2], [emp], [], [a1, a2])
    assert TOX_01.evaluate(snap) == []
