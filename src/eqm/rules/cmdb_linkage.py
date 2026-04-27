"""CMDB linkage rules: CMDB-01..02."""

from __future__ import annotations

from eqm.models import RecommendedAction, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


class _CMDB01:
    id = "CMDB-01"
    name = "Orphan entitlement"
    severity = Severity.LOW
    category = "cmdb_linkage"
    recommended_action = RecommendedAction.ROUTE_TO_ENTITLEMENT_OWNER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        valid_resource_ids = {r.id for r in snapshot.cmdb_resources}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            valid_links = [rid for rid in ent.linked_resource_ids
                           if rid in valid_resource_ids]
            if not valid_links:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=("Entitlement is not linked to any valid CMDB resource."),
                    evidence={"declared_links": ent.linked_resource_ids,
                              "valid_links": valid_links},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "link_to_resource",
                                   "_note": "Owner should add at least one valid resource id."},
                ))
        return violations


CMDB_01 = _CMDB01()
ALL_RULES.append(CMDB_01)
