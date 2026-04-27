"""Run all rules, reconcile against existing violations, return updated set."""

from __future__ import annotations

from dataclasses import dataclass

from eqm.models import Violation, WorkflowHistoryEntry, WorkflowState
from eqm.rules import ALL_RULES, ensure_rules_loaded
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


@dataclass(slots=True)
class EngineRunResult:
    violations: list[Violation]
    new_count: int
    resolved_count: int
    suppressed_rejected_count: int
    preserved_count: int


def _key(v: Violation) -> tuple[str, str, str]:
    return (v.rule_id, v.target_type, v.target_id)


def run_engine(snapshot: DataSnapshot,
               existing_violations: list[Violation]) -> EngineRunResult:
    ensure_rules_loaded()
    # Collect newly evaluated violations from all rules.
    detected: list[Violation] = []
    for rule in ALL_RULES:
        detected.extend(rule.evaluate(snapshot))

    existing_by_key: dict[tuple[str, str, str], Violation] = {
        _key(v): v for v in existing_violations
    }
    detected_by_key: dict[tuple[str, str, str], Violation] = {
        _key(v): v for v in detected
    }

    out: list[Violation] = []
    new_count = resolved_count = suppressed = preserved = 0

    used_ids = {v.id for v in existing_violations}

    # Pass 1: keep / resolve / suppress existing.
    for key, ev in existing_by_key.items():
        still_violating = key in detected_by_key
        if ev.workflow_state == WorkflowState.REJECTED:
            # Terminal — keep as-is, suppress new detection.
            out.append(ev)
            if still_violating:
                suppressed += 1
            continue
        if ev.workflow_state == WorkflowState.RESOLVED:
            out.append(ev)
            continue
        if still_violating:
            preserved += 1
            out.append(ev)  # preserve workflow_state, evidence, etc.
        else:
            # Auto-resolve.
            ev.workflow_history.append(WorkflowHistoryEntry(
                from_state=ev.workflow_state,
                to_state=WorkflowState.RESOLVED,
                actor="engine", timestamp=now_utc(),
                note="auto-resolved by drift",
            ))
            ev.workflow_state = WorkflowState.RESOLVED
            resolved_count += 1
            out.append(ev)

    # Pass 2: create new violations not present before AND not suppressed by REJECTED.
    suppressed_keys = {k for k, v in existing_by_key.items()
                       if v.workflow_state == WorkflowState.REJECTED}
    for key, det in detected_by_key.items():
        if key in existing_by_key:
            continue
        if key in suppressed_keys:
            continue
        new_id = next_violation_id(list(used_ids))
        used_ids.add(new_id)
        det.id = new_id
        out.append(det)
        new_count += 1

    return EngineRunResult(
        violations=out,
        new_count=new_count,
        resolved_count=resolved_count,
        suppressed_rejected_count=suppressed,
        preserved_count=preserved,
    )
