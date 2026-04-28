from eqm.models import AccessTier
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_02
from tests.rules.conftest import make_entitlement


def test_ent_q_02_tier1_missing_administrator_fires():
    e = make_entitlement(
        id="ENT-1", access_tier=AccessTier.ADMIN,
        pbl_description="This entitlement provides access to the production system for users."
    )
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-1"


def test_ent_q_02_tier4_missing_read_only_fires():
    e = make_entitlement(
        id="ENT-2", access_tier=AccessTier.GENERAL_RO,
        pbl_description="Provides users with general visibility into reporting dashboards."
    )
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-2"


def test_ent_q_02_tier1_with_administrator_passes():
    e = make_entitlement(
        id="ENT-3", access_tier=AccessTier.ADMIN,
        pbl_description="Grants administrator access to the production billing system."
    )
    assert ENT_Q_02.evaluate(DataSnapshot([e], [], [], [])) == []


def test_ent_q_02_tier2_3_not_evaluated():
    e = make_entitlement(
        id="ENT-4", access_tier=AccessTier.READ_WRITE,
        pbl_description="A short one but no template required for tier 2."
    )
    assert ENT_Q_02.evaluate(DataSnapshot([e], [], [], [])) == []
