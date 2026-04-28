from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_01
from tests.rules.conftest import make_entitlement


def test_ent_q_01_short_description_fires():
    e = make_entitlement(id="ENT-1", pbl_description="too short")
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].rule_id == "ENT-Q-01"
    assert violations[0].target_id == "ENT-1"
    assert violations[0].severity == "low"


def test_ent_q_01_banned_phrase_fires():
    e = make_entitlement(id="ENT-2",
                         pbl_description="This entitlement lets you do things in the system.")
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-2"


def test_ent_q_01_clean_description_passes():
    e = make_entitlement()  # uses default well-formed PBL
    snap = DataSnapshot([e], [], [], [])
    assert ENT_Q_01.evaluate(snap) == []
