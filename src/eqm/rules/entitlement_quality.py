"""Entitlement quality rules: ENT-Q-01..04."""

from __future__ import annotations

from eqm.models import (
    RecommendedAction,
    Severity,
    Violation,
)
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc

BANNED_PHRASES = ["access stuff", "do things", "admin access"]


class _ENTQ01:
    id = "ENT-Q-01"
    name = "PBL completeness"
    severity = Severity.LOW
    category = "entitlement_quality"
    recommended_action = RecommendedAction.UPDATE_ENTITLEMENT_FIELD

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            desc = (ent.pbl_description or "").strip().lower()
            reasons: list[str] = []
            if len(desc) < 20:
                reasons.append(f"length={len(desc)} < 20")
            for phrase in BANNED_PHRASES:
                if phrase in desc:
                    reasons.append(f"banned phrase: '{phrase}'")
            if reasons:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=f"PBL description fails completeness check: {'; '.join(reasons)}",
                    evidence={"pbl_description": ent.pbl_description, "reasons": reasons},
                    recommended_action=self.recommended_action,
                    suggested_fix={"pbl_description": "[Owner — please rewrite this description "
                                   "to clearly state what access is granted, on which system, "
                                   "and to whom.]"},
                ))
        return violations


ENT_Q_01 = _ENTQ01()
ALL_RULES.append(ENT_Q_01)
