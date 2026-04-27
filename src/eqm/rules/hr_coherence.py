"""HR coherence rules: HR-01..04."""

from __future__ import annotations

from eqm.models import RecommendedAction, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


class _HR01:
    id = "HR-01"
    name = "Role mismatch"
    severity = Severity.MEDIUM
    category = "hr_coherence"
    recommended_action = RecommendedAction.AUTO_REVOKE_ASSIGNMENT

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            emp = emp_by_id.get(a.employee_id)
            if not ent or not emp:
                continue
            if emp.current_role not in ent.acceptable_roles:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Employee role '{emp.current_role.value}' not in "
                                 f"entitlement.acceptable_roles "
                                 f"{[r.value for r in ent.acceptable_roles]}."),
                    evidence={"employee_id": emp.id,
                              "employee_role": emp.current_role.value,
                              "entitlement_id": ent.id,
                              "acceptable_roles": [r.value for r in ent.acceptable_roles]},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_01 = _HR01()
ALL_RULES.append(HR_01)
