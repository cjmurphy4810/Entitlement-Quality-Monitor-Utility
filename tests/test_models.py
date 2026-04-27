from eqm.models import (
    AccessTier,
    Criticality,
    Division,
    EmployeeStatus,
    RecommendedAction,
    ResourceType,
    Role,
    Severity,
    WorkflowState,
)


def test_access_tier_values():
    assert AccessTier.ADMIN == 1
    assert AccessTier.GENERAL_RO == 4
    assert int(AccessTier.READ_WRITE) == 2


def test_role_values():
    assert {r.value for r in Role} == {
        "developer", "operations", "business_user", "business_analyst", "customer",
    }


def test_division_values():
    assert "cyber_tech" in {d.value for d in Division}
    assert "legal_compliance" in {d.value for d in Division}
    assert len(Division) == 9


def test_workflow_states_complete():
    assert {s.value for s in WorkflowState} == {
        "open", "pending_approval", "approved", "rejected", "manual_repair", "resolved",
    }


def test_recommended_actions_complete():
    assert {a.value for a in RecommendedAction} == {
        "auto_revoke_assignment",
        "update_entitlement_field",
        "route_to_entitlement_owner",
        "route_to_user_manager",
        "route_to_compliance",
    }


def test_severity_levels():
    assert {s.value for s in Severity} == {"low", "medium", "high", "critical"}


def test_criticality_levels():
    assert {c.value for c in Criticality} == {"low", "medium", "high", "critical"}


def test_employee_status():
    assert {s.value for s in EmployeeStatus} == {"active", "on_leave", "terminated"}


def test_resource_types():
    assert {t.value for t in ResourceType} == {
        "application", "share_drive", "website", "database", "api",
    }
