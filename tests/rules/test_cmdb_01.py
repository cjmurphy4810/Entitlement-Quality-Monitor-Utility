from eqm.rules.base import DataSnapshot
from eqm.rules.cmdb_linkage import CMDB_01
from tests.rules.conftest import make_entitlement, make_resource


def test_cmdb_01_orphan_fires():
    # Entitlement declares a resource link that does not exist in CMDB — treat as orphan.
    e = make_entitlement(id="ENT-1", linked_resource_ids=["RES-MISSING"])
    violations = CMDB_01.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-1"
    assert violations[0].severity == "low"


def test_cmdb_01_linked_passes():
    res = make_resource(id="RES-1")
    e = make_entitlement(linked_resource_ids=["RES-1"])
    assert CMDB_01.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_cmdb_01_dangling_link_still_fires():
    # Linked id refers to a resource that does NOT exist — treat as orphan.
    e = make_entitlement(id="ENT-2", linked_resource_ids=["RES-NONEXISTENT"])
    violations = CMDB_01.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1
