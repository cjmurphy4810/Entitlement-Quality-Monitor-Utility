from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot


def test_data_snapshot_is_immutable_lists():
    s = DataSnapshot(entitlements=[], hr_employees=[],
                     cmdb_resources=[], assignments=[])
    assert isinstance(s.entitlements, tuple)
    assert isinstance(s.hr_employees, tuple)


def test_rules_registry_starts_empty():
    # Will be populated by later tasks; the registry exists
    assert isinstance(ALL_RULES, list)
