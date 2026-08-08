"""Shared presentation projections for EQM violations."""

from __future__ import annotations

from eqm.models import Violation


def project_violation(
    v: Violation,
    emp_by_id: dict,
    asn_by_id: dict,
    *,
    include_internal: bool = False,
) -> dict:
    """Adapt a violation to the Appian-friendly shape, resolving user context."""
    emp_id, emp_name = "n/a", "n/a"
    if v.target_type == "employee":
        emp_id = v.target_id
        emp = emp_by_id.get(v.target_id)
        if emp:
            emp_name = emp["full_name"]
    elif v.target_type == "assignment":
        asn = asn_by_id.get(v.target_id)
        if asn:
            emp_id = asn["employee_id"]
            emp = emp_by_id.get(emp_id)
            if emp:
                emp_name = emp["full_name"]
    out = {
        "violationId": v.id,
        "userId": emp_id,
        "userName": emp_name,
        "ruleId": v.rule_id,
        "ruleName": v.rule_name,
        "status": v.workflow_state.value.replace("_", " ").title(),
        "severity": v.severity.value.title(),
        "reason": v.explanation,
        "targetType": v.target_type,
        "targetId": v.target_id,
        "recommendedAction": v.recommended_action.value,
        "detectedAt": v.detected_at.isoformat(),
    }
    if include_internal:
        out["evidence"] = v.evidence
        out["suggestedFix"] = v.suggested_fix
        out["workflowHistory"] = [h.model_dump(mode="json") for h in v.workflow_history]
    return out
