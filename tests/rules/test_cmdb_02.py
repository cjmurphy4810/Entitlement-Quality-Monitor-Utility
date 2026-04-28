from eqm.models import AccessTier, Criticality
from eqm.rules.base import DataSnapshot
from eqm.rules.cmdb_linkage import CMDB_02
from tests.rules.conftest import make_entitlement, make_resource


def test_cmdb_02_tier4_on_high_criticality_fires():
    res = make_resource(id="RES-1", criticality=Criticality.HIGH)
    e = make_entitlement(id="ENT-1", access_tier=AccessTier.GENERAL_RO,
                         linked_resource_ids=["RES-1"])
    violations = CMDB_02.evaluate(DataSnapshot([e], [], [res], []))
    assert len(violations) == 1
    assert violations[0].severity == "high"


def test_cmdb_02_tier3_on_critical_fires():
    res = make_resource(id="RES-1", criticality=Criticality.CRITICAL)
    e = make_entitlement(access_tier=AccessTier.ELEVATED_RO,
                         linked_resource_ids=["RES-1"])
    violations = CMDB_02.evaluate(DataSnapshot([e], [], [res], []))
    assert len(violations) == 1


def test_cmdb_02_tier2_on_high_passes():
    res = make_resource(id="RES-1", criticality=Criticality.HIGH)
    e = make_entitlement(access_tier=AccessTier.READ_WRITE,
                         linked_resource_ids=["RES-1"])
    assert CMDB_02.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_cmdb_02_tier4_on_low_passes():
    res = make_resource(id="RES-1", criticality=Criticality.LOW)
    e = make_entitlement(access_tier=AccessTier.GENERAL_RO,
                         linked_resource_ids=["RES-1"])
    assert CMDB_02.evaluate(DataSnapshot([e], [], [res], [])) == []
