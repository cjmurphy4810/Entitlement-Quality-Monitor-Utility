from eqm.models import AccessTier, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_02
from tests.rules.conftest import make_assignment, make_employee, make_entitlement, make_resource


def test_tox_02_same_user_dev_admin_and_ops_admin_on_same_resource_fires():
    res = make_resource(id="RES-1", environment="prod")
    e_dev = make_entitlement(id="ENT-DEV", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.DEVELOPER],
                             linked_resource_ids=["RES-1"])
    e_ops = make_entitlement(id="ENT-OPS", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.OPERATIONS],
                             linked_resource_ids=["RES-1"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-DEV")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-OPS")
    snap = DataSnapshot([e_dev, e_ops], [emp], [res], [a1, a2])
    violations = TOX_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "critical"


def test_tox_02_different_resources_passes():
    r1 = make_resource(id="RES-1", environment="prod")
    r2 = make_resource(id="RES-2", environment="prod")
    e_dev = make_entitlement(id="ENT-DEV", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.DEVELOPER],
                             linked_resource_ids=["RES-1"])
    e_ops = make_entitlement(id="ENT-OPS", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.OPERATIONS],
                             linked_resource_ids=["RES-2"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-DEV")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-OPS")
    assert TOX_02.evaluate(DataSnapshot([e_dev, e_ops], [emp], [r1, r2], [a1, a2])) == []
