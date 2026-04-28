"""HR coherence rules: HR-01..04."""

from __future__ import annotations

from datetime import timedelta

from eqm.models import EmployeeStatus, RecommendedAction, Severity, Violation
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


class _HR02:
    id = "HR-02"
    name = "Division mismatch"
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
            if emp.current_division != ent.division:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Employee division '{emp.current_division.value}' "
                                 f"does not match entitlement division "
                                 f"'{ent.division.value}'."),
                    evidence={"employee_id": emp.id,
                              "employee_division": emp.current_division.value,
                              "entitlement_id": ent.id,
                              "entitlement_division": ent.division.value},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_02 = _HR02()
ALL_RULES.append(HR_02)


LEGACY_DAYS_THRESHOLD = 30


class _HR03:
    id = "HR-03"
    name = "Legacy entitlement after role change"
    severity = Severity.HIGH
    category = "hr_coherence"
    recommended_action = RecommendedAction.ROUTE_TO_USER_MANAGER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        cutoff = now_utc() - timedelta(days=LEGACY_DAYS_THRESHOLD)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            emp = emp_by_id.get(a.employee_id)
            if not ent or not emp:
                continue
            # Find the most recent role transition (where ended_at != None and is the latest)
            ended_entries = [h for h in emp.role_history if h.ended_at is not None]
            if not ended_entries:
                continue
            last_change_at = max(h.ended_at for h in ended_entries)
            if last_change_at > cutoff:
                continue  # too recent
            if a.granted_at >= last_change_at:
                continue  # granted after the change — not legacy
            # Was the prior role acceptable but current role isn't?
            if emp.current_role in ent.acceptable_roles:
                continue  # still appropriate
            prior_roles = {h.role for h in ended_entries}
            if not (prior_roles & set(ent.acceptable_roles)):
                continue  # never was appropriate; that's HR-01, not HR-03
            vid = next_violation_id(existing_ids)
            existing_ids.append(vid)
            violations.append(Violation(
                id=vid, rule_id=self.id, rule_name=self.name,
                severity=self.severity, detected_at=now_utc(),
                target_type="assignment", target_id=a.id,
                explanation=(f"Assignment was appropriate under prior role(s) "
                             f"but employee's current role is "
                             f"'{emp.current_role.value}'. Last role change "
                             f"was {last_change_at.isoformat()}."),
                evidence={"employee_id": emp.id,
                          "current_role": emp.current_role.value,
                          "prior_roles": [r.value for r in prior_roles],
                          "last_role_change_at": last_change_at.isoformat(),
                          "granted_at": a.granted_at.isoformat()},
                recommended_action=self.recommended_action,
                suggested_fix={"_action": "delete_assignment",
                               "_note": "Manager should confirm before revocation."},
            ))
        return violations


HR_03 = _HR03()
ALL_RULES.append(HR_03)


class _HR04:
    id = "HR-04"
    name = "Terminated user holds active assignment"
    severity = Severity.CRITICAL
    category = "hr_coherence"
    recommended_action = RecommendedAction.AUTO_REVOKE_ASSIGNMENT

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for a in snapshot.assignments:
            if not a.active:
                continue
            emp = emp_by_id.get(a.employee_id)
            if not emp:
                continue
            if emp.status == EmployeeStatus.TERMINATED:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Terminated employee {emp.id} ({emp.full_name}) "
                                 f"still holds active assignment {a.id}."),
                    evidence={"employee_id": emp.id,
                              "terminated_at": (emp.terminated_at.isoformat()
                                                if emp.terminated_at else None),
                              "entitlement_id": a.entitlement_id},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_04 = _HR04()
ALL_RULES.append(HR_04)
