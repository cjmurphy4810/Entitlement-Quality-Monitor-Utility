"""Violation workflow state machine."""

from __future__ import annotations

from datetime import UTC, datetime

from eqm.models import Violation, WorkflowHistoryEntry, WorkflowState


class IllegalTransition(Exception):  # noqa: N818
    """Raised when a requested workflow transition is not allowed."""

    def __init__(self, current: WorkflowState, to: WorkflowState,
                 legal: list[WorkflowState]) -> None:
        super().__init__(f"Cannot transition {current.value} -> {to.value}. "
                          f"Legal: {[s.value for s in legal]}")
        self.current = current
        self.to = to
        self.legal = legal


LEGAL_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.OPEN: {WorkflowState.PENDING_APPROVAL},
    WorkflowState.PENDING_APPROVAL: {
        WorkflowState.APPROVED,
        WorkflowState.REJECTED,
        WorkflowState.MANUAL_REPAIR,
    },
    WorkflowState.APPROVED: {WorkflowState.RESOLVED},
    WorkflowState.MANUAL_REPAIR: {WorkflowState.RESOLVED},
    WorkflowState.REJECTED: set(),  # terminal
    WorkflowState.RESOLVED: set(),  # terminal
}


def legal_next_states(current: WorkflowState) -> list[WorkflowState]:
    return sorted(LEGAL_TRANSITIONS[current], key=lambda s: s.value)


def transition(violation: Violation, *, to: WorkflowState, actor: str,
               note: str | None, override_fix: dict | None = None) -> None:
    legal = LEGAL_TRANSITIONS[violation.workflow_state]
    if to not in legal:
        raise IllegalTransition(violation.workflow_state, to, sorted(legal, key=lambda s: s.value))
    if to == WorkflowState.REJECTED and not note:
        raise IllegalTransition(violation.workflow_state, to, list(legal))  # rejection requires reason
    entry = WorkflowHistoryEntry(
        from_state=violation.workflow_state, to_state=to, actor=actor,
        timestamp=datetime.now(UTC), note=note, override_fix=override_fix,
    )
    violation.workflow_history.append(entry)
    violation.workflow_state = to
