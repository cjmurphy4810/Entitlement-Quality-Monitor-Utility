from eqm.rules import ALL_RULES, ensure_rules_loaded


def test_all_13_rules_registered():
    ensure_rules_loaded()
    ids = sorted(r.id for r in ALL_RULES)
    assert ids == sorted([
        "ENT-Q-01", "ENT-Q-02", "ENT-Q-03", "ENT-Q-04",
        "TOX-01", "TOX-02", "TOX-03",
        "HR-01", "HR-02", "HR-03", "HR-04",
        "CMDB-01", "CMDB-02",
    ])


def test_no_duplicate_rule_ids():
    ensure_rules_loaded()
    ids = [r.id for r in ALL_RULES]
    assert len(ids) == len(set(ids))
