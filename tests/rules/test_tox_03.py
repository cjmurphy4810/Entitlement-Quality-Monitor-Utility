from eqm.models import AccessTier, Division
from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_03
from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_tox_03_three_divisions_fires():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.ADMIN, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE, Division.HR])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(3)]
    snap = DataSnapshot(ents, [emp], [], asns)
    violations = TOX_03.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "high"


def test_tox_03_two_divisions_passes():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.ADMIN, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(2)]
    assert TOX_03.evaluate(DataSnapshot(ents, [emp], [], asns)) == []


def test_tox_03_three_divisions_but_not_tier1_passes():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.READ_WRITE, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE, Division.HR])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(3)]
    assert TOX_03.evaluate(DataSnapshot(ents, [emp], [], asns)) == []
