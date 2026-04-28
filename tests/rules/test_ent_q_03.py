from eqm.models import AccessTier, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_03
from tests.rules.conftest import make_entitlement


def test_tier1_with_customer_fires():
    e = make_entitlement(id="ENT-1", access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.OPERATIONS, Role.CUSTOMER])
    violations = ENT_Q_03.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1


def test_tier1_with_business_user_fires():
    e = make_entitlement(id="ENT-2", access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.BUSINESS_USER])
    violations = ENT_Q_03.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1


def test_tier1_with_developer_passes():
    e = make_entitlement(access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.DEVELOPER, Role.OPERATIONS])
    assert ENT_Q_03.evaluate(DataSnapshot([e], [], [], [])) == []


def test_tier2_with_customer_passes():
    e = make_entitlement(access_tier=AccessTier.READ_WRITE,
                         acceptable_roles=[Role.CUSTOMER])
    assert ENT_Q_03.evaluate(DataSnapshot([e], [], [], [])) == []
