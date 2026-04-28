import pytest

from eqm.engine import run_engine
from eqm.rules.base import DataSnapshot
from eqm.scenarios import SCENARIOS, run_scenario
from eqm.seed import SeedConfig, generate_seed


def _bundle():
    return generate_seed(SeedConfig(num_entitlements=50, num_employees=50,
                                     num_resources=10, num_assignments=80, seed=5))


def test_all_seven_scenarios_registered():
    assert set(SCENARIOS.keys()) == {
        "terminated_user_with_admin", "sod_payment_breach",
        "legacy_entitlements_after_promotion", "bad_pbl_batch",
        "tier_role_mismatch", "orphan_entitlements", "kitchen_sink",
    }


@pytest.mark.parametrize("name", [
    "terminated_user_with_admin", "sod_payment_breach",
    "legacy_entitlements_after_promotion", "bad_pbl_batch",
    "tier_role_mismatch", "orphan_entitlements", "kitchen_sink",
])
def test_scenario_produces_expected_violations(name):
    bundle = _bundle()
    run_scenario(name, bundle)
    snap = DataSnapshot(bundle.entitlements, bundle.hr_employees,
                        bundle.cmdb_resources, bundle.assignments)
    result = run_engine(snap, existing_violations=[])
    assert result.new_count > 0


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        run_scenario("nope", _bundle())
