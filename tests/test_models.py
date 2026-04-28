from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from eqm.models import (
    AccessTier,
    Assignment,
    CMDBResource,
    Criticality,
    Division,
    EmployeeStatus,
    Entitlement,
    HREmployee,
    RecommendedAction,
    ResourceType,
    Role,
    RoleHistoryEntry,
    Severity,
    Violation,
    WorkflowState,
)

NOW = datetime.now(UTC)


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


def test_entitlement_minimal_valid():
    e = Entitlement(
        id="ENT-00001",
        name="Prod DB Admin",
        pbl_description="Grants administrator access to the production customer database.",
        access_tier=1,
        acceptable_roles=["operations"],
        division="tech_ops",
        linked_resource_ids=["RES-00001"],
        sod_tags=[],
        created_at=NOW,
        updated_at=NOW,
    )
    assert e.access_tier == 1
    assert e.id == "ENT-00001"


def test_entitlement_rejects_unknown_role():
    with pytest.raises(ValidationError):
        Entitlement(
            id="ENT-2",
            name="X",
            pbl_description="Some description that is long enough.",
            access_tier=2,
            acceptable_roles=["wizard"],
            division="hr",
            linked_resource_ids=[],
            created_at=NOW,
            updated_at=NOW,
        )


def test_hr_employee_with_history():
    emp = HREmployee(
        id="EMP-00001",
        full_name="Alice Lee",
        email="alice@example.com",
        current_role="operations",
        current_division="tech_ops",
        status="active",
        role_history=[
            RoleHistoryEntry(role="developer", division="tech_dev",
                             started_at=NOW - timedelta(days=400), ended_at=NOW - timedelta(days=60)),
            RoleHistoryEntry(role="operations", division="tech_ops",
                             started_at=NOW - timedelta(days=60), ended_at=None),
        ],
        manager_id=None,
        hired_at=NOW - timedelta(days=400),
        terminated_at=None,
    )
    assert emp.role_history[-1].ended_at is None


def test_cmdb_resource_environment_constraint():
    with pytest.raises(ValidationError):
        CMDBResource(
            id="RES-1", name="x", type="application", criticality="high",
            owner_division="hr", environment="staging-2",
            linked_entitlement_ids=[], description="x",
        )


def test_assignment_active_default_true():
    a = Assignment(
        id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1",
        granted_at=NOW, granted_by="system", last_certified_at=None,
    )
    assert a.active is True


def test_violation_default_state_open():
    v = Violation(
        id="VIO-1", rule_id="ENT-Q-01", rule_name="PBL completeness",
        severity="low", detected_at=NOW,
        target_type="entitlement", target_id="ENT-1",
        explanation="Description too short", evidence={"length": 4},
        recommended_action="update_entitlement_field",
        suggested_fix={"pbl_description": "..."},
    )
    assert v.workflow_state == "open"
    assert v.workflow_history == []
