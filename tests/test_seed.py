from eqm.models import Assignment, CMDBResource, Entitlement, HREmployee
from eqm.seed import SeedConfig, generate_seed


def test_generate_seed_default_counts():
    cfg = SeedConfig(num_entitlements=10, num_employees=20, num_resources=5,
                     num_assignments=30, seed=42)
    bundle = generate_seed(cfg)
    assert len(bundle.entitlements) == 10
    assert len(bundle.hr_employees) == 20
    assert len(bundle.cmdb_resources) == 5
    assert len(bundle.assignments) == 30


def test_generate_seed_is_deterministic():
    cfg = SeedConfig(num_entitlements=5, num_employees=5, num_resources=3,
                     num_assignments=4, seed=123)
    a = generate_seed(cfg)
    b = generate_seed(cfg)
    assert [e.id for e in a.entitlements] == [e.id for e in b.entitlements]
    assert [e.full_name for e in a.hr_employees] == [e.full_name for e in b.hr_employees]


def test_seed_records_are_valid_models():
    cfg = SeedConfig(num_entitlements=3, num_employees=3, num_resources=2,
                     num_assignments=2, seed=1)
    b = generate_seed(cfg)
    for e in b.entitlements:
        assert isinstance(e, Entitlement)
    for emp in b.hr_employees:
        assert isinstance(emp, HREmployee)
    for r in b.cmdb_resources:
        assert isinstance(r, CMDBResource)
    for a in b.assignments:
        assert isinstance(a, Assignment)


def test_seed_assignments_reference_real_entities():
    cfg = SeedConfig(num_entitlements=5, num_employees=5, num_resources=2,
                     num_assignments=10, seed=7)
    b = generate_seed(cfg)
    emp_ids = {e.id for e in b.hr_employees}
    ent_ids = {e.id for e in b.entitlements}
    for a in b.assignments:
        assert a.employee_id in emp_ids
        assert a.entitlement_id in ent_ids
