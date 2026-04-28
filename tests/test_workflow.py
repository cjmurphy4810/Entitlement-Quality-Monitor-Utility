import pytest

from eqm.models import Violation, WorkflowState
from eqm.workflow import IllegalTransition, transition
from tests.rules.conftest import NOW


def _v(state: WorkflowState) -> Violation:
    return Violation(
        id="VIO-1", rule_id="ENT-Q-01", rule_name="x",
        severity="low", detected_at=NOW,
        target_type="entitlement", target_id="ENT-1",
        explanation="x", evidence={},
        recommended_action="update_entitlement_field",
        suggested_fix={}, workflow_state=state,
    )


def test_open_to_pending_approval_legal():
    v = _v(WorkflowState.OPEN)
    transition(v, to=WorkflowState.PENDING_APPROVAL, actor="appian", note=None)
    assert v.workflow_state == WorkflowState.PENDING_APPROVAL
    assert len(v.workflow_history) == 1


def test_pending_to_approved_legal():
    v = _v(WorkflowState.PENDING_APPROVAL)
    transition(v, to=WorkflowState.APPROVED, actor="alice@example.com",
               note="approved")
    assert v.workflow_state == WorkflowState.APPROVED


def test_pending_to_rejected_requires_note():
    v = _v(WorkflowState.PENDING_APPROVAL)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.REJECTED, actor="x", note=None)
    transition(v, to=WorkflowState.REJECTED, actor="x", note="not a real issue")
    assert v.workflow_state == WorkflowState.REJECTED


def test_open_to_approved_illegal():
    v = _v(WorkflowState.OPEN)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.APPROVED, actor="x", note=None)


def test_resolved_terminal():
    v = _v(WorkflowState.RESOLVED)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.OPEN, actor="x", note=None)


def test_override_fix_recorded():
    v = _v(WorkflowState.PENDING_APPROVAL)
    transition(v, to=WorkflowState.APPROVED, actor="alice",
               note="modified", override_fix={"pbl_description": "new"})
    assert v.workflow_history[-1].override_fix == {"pbl_description": "new"}
