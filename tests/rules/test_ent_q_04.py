from eqm.models import AccessTier, Division, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_04
from tests.rules.conftest import make_entitlement, make_resource


def test_hr_division_with_developer_fires():
    e = make_entitlement(id="ENT-1", division=Division.HR,
                         access_tier=AccessTier.READ_WRITE,
                         acceptable_roles=[Role.DEVELOPER, Role.BUSINESS_USER])
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_04.evaluate(snap)
    assert len(violations) == 1
    assert "developer" in violations[0].explanation.lower()


def test_legal_compliance_tier1_on_prod_fires():
    res = make_resource(id="RES-1", environment="prod")
    e = make_entitlement(id="ENT-2", division=Division.LEGAL_COMPLIANCE,
                         access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.OPERATIONS],
                         linked_resource_ids=["RES-1"])
    snap = DataSnapshot([e], [], [res], [])
    violations = ENT_Q_04.evaluate(snap)
    assert len(violations) == 1


def test_legal_compliance_tier2_on_prod_passes():
    res = make_resource(id="RES-1", environment="prod")
    e = make_entitlement(division=Division.LEGAL_COMPLIANCE,
                         access_tier=AccessTier.READ_WRITE,
                         linked_resource_ids=["RES-1"])
    assert ENT_Q_04.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_tech_dev_with_developer_passes():
    e = make_entitlement(division=Division.TECH_DEV,
                         acceptable_roles=[Role.DEVELOPER])
    assert ENT_Q_04.evaluate(DataSnapshot([e], [], [], [])) == []
