"""Toxic combination rules: TOX-01..03."""

from __future__ import annotations

from collections import defaultdict

from eqm.models import AccessTier, RecommendedAction, Role, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc

SOD_PAIRS = [("payment_initiate", "payment_approve"),
             ("trade_initiate", "trade_settle")]


class _TOX01:
    id = "TOX-01"
    name = "Maker-checker conflict"
    severity = Severity.CRITICAL
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        # employee_id -> set of sod_tags they hold via active assignments
        tags_by_emp: dict[str, set[str]] = defaultdict(set)
        ents_by_emp: dict[str, set[str]] = defaultdict(set)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent:
                continue
            for tag in ent.sod_tags:
                tags_by_emp[a.employee_id].add(tag)
                ents_by_emp[a.employee_id].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for emp_id, tags in tags_by_emp.items():
            for left, right in SOD_PAIRS:
                if left in tags and right in tags:
                    vid = next_violation_id(existing_ids)
                    existing_ids.append(vid)
                    violations.append(Violation(
                        id=vid, rule_id=self.id, rule_name=self.name,
                        severity=self.severity, detected_at=now_utc(),
                        target_type="employee", target_id=emp_id,
                        explanation=(f"Employee holds both '{left}' and '{right}' "
                                     f"entitlements — segregation of duties violation."),
                        evidence={"sod_pair": [left, right],
                                  "entitlement_ids": sorted(ents_by_emp[emp_id])},
                        recommended_action=self.recommended_action,
                        suggested_fix={"_action": "compliance_review",
                                       "_choices": ["revoke_left_side", "revoke_right_side"],
                                       "_pair": [left, right]},
                    ))
        return violations


TOX_01 = _TOX01()
ALL_RULES.append(TOX_01)


class _TOX02:
    id = "TOX-02"
    name = "Dev + Prod-Admin on same application"
    severity = Severity.CRITICAL
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        # Group active assignments by employee then by linked resource
        # collecting roles seen per (employee, resource).
        per_pair: dict[tuple[str, str], dict[str, set[str]]] = {}
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent or ent.access_tier != AccessTier.ADMIN:
                continue
            for rid in ent.linked_resource_ids:
                key = (a.employee_id, rid)
                bucket = per_pair.setdefault(key, {"dev": set(), "ops": set()})
                if Role.DEVELOPER in ent.acceptable_roles:
                    bucket["dev"].add(ent.id)
                if Role.OPERATIONS in ent.acceptable_roles:
                    bucket["ops"].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for (emp_id, res_id), buckets in per_pair.items():
            if buckets["dev"] and buckets["ops"]:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="employee", target_id=emp_id,
                    explanation=(f"Employee holds both Developer Tier-1 and Operations "
                                 f"Tier-1 access on resource {res_id}."),
                    evidence={"resource_id": res_id,
                              "developer_admin_entitlements": sorted(buckets["dev"]),
                              "operations_admin_entitlements": sorted(buckets["ops"])},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "compliance_review",
                                   "_choices": ["revoke_developer_side", "revoke_operations_side"]},
                ))
        return violations


TOX_02 = _TOX02()
ALL_RULES.append(TOX_02)


class _TOX03:
    id = "TOX-03"
    name = "Tier-1 in 3+ divisions"
    severity = Severity.HIGH
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    THRESHOLD = 3

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        divs_by_emp: dict[str, set[str]] = defaultdict(set)
        ent_ids_by_emp: dict[str, set[str]] = defaultdict(set)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent or ent.access_tier != AccessTier.ADMIN:
                continue
            divs_by_emp[a.employee_id].add(ent.division.value)
            ent_ids_by_emp[a.employee_id].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for emp_id, divs in divs_by_emp.items():
            if len(divs) >= self.THRESHOLD:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="employee", target_id=emp_id,
                    explanation=(f"Employee holds Tier-1 (Admin) in {len(divs)} "
                                 f"divisions: {sorted(divs)}"),
                    evidence={"divisions": sorted(divs),
                              "entitlement_ids": sorted(ent_ids_by_emp[emp_id])},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "compliance_review",
                                   "_note": "Reduce Tier-1 footprint to ≤2 divisions"},
                ))
        return violations


TOX_03 = _TOX03()
ALL_RULES.append(TOX_03)
