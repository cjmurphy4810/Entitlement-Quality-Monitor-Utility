from eqm.seed import SeedConfig, generate_seed
from eqm.simulator import drift_tick


def test_drift_tick_returns_summary_and_mutates_state():
    bundle = generate_seed(SeedConfig(num_entitlements=20, num_employees=30,
                                      num_resources=5, num_assignments=40, seed=1))
    summary = drift_tick(bundle, tick_number=1)
    assert summary.tick_number == 1
    assert summary.changes
    # At least one mutation happened.
    assert (summary.new_employees + summary.role_changes + summary.terminations
            + summary.new_assignments + summary.new_entitlements) > 0


def test_drift_tick_is_deterministic_with_same_tick_number():
    cfg = SeedConfig(num_entitlements=10, num_employees=10, num_resources=3,
                     num_assignments=10, seed=99)
    a = generate_seed(cfg)
    b = generate_seed(cfg)
    sa = drift_tick(a, tick_number=42)
    sb = drift_tick(b, tick_number=42)
    assert sa.changes == sb.changes
