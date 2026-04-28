from eqm.rules.base import next_violation_id, now_utc


def test_next_violation_id_increments():
    a = next_violation_id(["VIO-00001", "VIO-00003"])
    assert a == "VIO-00004"


def test_next_violation_id_empty():
    assert next_violation_id([]) == "VIO-00001"


def test_now_utc_returns_aware():
    n = now_utc()
    assert n.tzinfo is not None
