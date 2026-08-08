from datetime import UTC, datetime

from eqm.models import RecommendedAction, Severity, Violation, WorkflowState
from eqm.projections import project_violation


def test_project_violation_preserves_public_list_and_detail_contract():
    """Removing a public field or internal detail would break API consumers."""
    violation = Violation(
        id="VIO-1", rule_id="ENT-Q-01", rule_name="PBL completeness",
        severity=Severity.HIGH, detected_at=datetime(2026, 1, 2, tzinfo=UTC),
        target_type="assignment", target_id="ASN-1", explanation="Missing PBL",
        evidence={"pbl_description": ""},
        recommended_action=RecommendedAction.UPDATE_ENTITLEMENT_FIELD,
        suggested_fix={"access_tier": 2}, workflow_state=WorkflowState.OPEN,
    )
    employees = {"EMP-1": {"id": "EMP-1", "full_name": "Ada Lovelace"}}
    assignments = {"ASN-1": {"id": "ASN-1", "employee_id": "EMP-1"}}

    row = project_violation(violation, employees, assignments)
    detail = project_violation(violation, employees, assignments, include_internal=True)

    assert set(row) == {
        "violationId", "userId", "userName", "ruleId", "ruleName", "status",
        "severity", "reason", "targetType", "targetId", "recommendedAction", "detectedAt",
    }
    assert row["userName"] == "Ada Lovelace"
    assert detail["suggestedFix"] == {"access_tier": 2}
    assert detail["evidence"] == {"pbl_description": ""}
    assert detail["workflowHistory"] == []
