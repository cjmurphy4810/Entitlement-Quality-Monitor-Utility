"""Entitlement quality rules: ENT-Q-01..04."""

from __future__ import annotations

from eqm.models import (
    AccessTier,
    RecommendedAction,
    Role,
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


class _ENTQ02:
    id = "ENT-Q-02"
    name = "PBL template match"
    severity = Severity.MEDIUM
    category = "entitlement_quality"
    recommended_action = RecommendedAction.ROUTE_TO_ENTITLEMENT_OWNER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            desc = (ent.pbl_description or "").lower()
            reason = None
            if ent.access_tier == AccessTier.ADMIN and "administrator" not in desc:
                reason = "Tier-1 PBL must mention 'administrator'"
            elif ent.access_tier == AccessTier.GENERAL_RO and "read-only" not in desc and "read only" not in desc:
                reason = "Tier-4 PBL must mention 'read-only'"
            if reason:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=reason,
                    evidence={"access_tier": int(ent.access_tier),
                              "pbl_description": ent.pbl_description},
                    recommended_action=self.recommended_action,
                    suggested_fix={"pbl_description":
                        f"[Owner — rewrite to match Tier-{int(ent.access_tier)} template "
                        f"({'administrator + system name' if ent.access_tier == AccessTier.ADMIN else 'read-only + system name'}).]"},
                ))
        return violations


ENT_Q_02 = _ENTQ02()
ALL_RULES.append(ENT_Q_02)


class _ENTQ03:
    id = "ENT-Q-03"
    name = "Tier vs role coherence"
    severity = Severity.HIGH
    category = "entitlement_quality"
    recommended_action = RecommendedAction.UPDATE_ENTITLEMENT_FIELD

    FORBIDDEN_AT_TIER_1 = {Role.CUSTOMER, Role.BUSINESS_USER}

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            if ent.access_tier != AccessTier.ADMIN:
                continue
            forbidden = [r for r in ent.acceptable_roles if r in self.FORBIDDEN_AT_TIER_1]
            if forbidden:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                cleaned = [r for r in ent.acceptable_roles if r not in self.FORBIDDEN_AT_TIER_1]
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=(f"Tier-1 (Admin) entitlement lists forbidden roles: "
                                 f"{[r.value for r in forbidden]}"),
                    evidence={"access_tier": 1,
                              "acceptable_roles": [r.value for r in ent.acceptable_roles],
                              "forbidden_roles": [r.value for r in forbidden]},
                    recommended_action=self.recommended_action,
                    suggested_fix={"acceptable_roles": [r.value for r in cleaned]},
                ))
        return violations


ENT_Q_03 = _ENTQ03()
ALL_RULES.append(ENT_Q_03)
