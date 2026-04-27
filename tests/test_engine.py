from eqm.engine import EngineRunResult, run_engine
from eqm.models import WorkflowState
from eqm.rules.base import DataSnapshot
from tests.rules.conftest import make_entitlement


def _bad_snapshot() -> DataSnapshot:
    # An entitlement with PBL too short -> ENT-Q-01.
    e = make_entitlement(id="ENT-1", pbl_description="x")
    return DataSnapshot([e], [], [], [])


def test_engine_emits_violations_first_run():
    snap = _bad_snapshot()
    result = run_engine(snap, existing_violations=[])
    assert isinstance(result, EngineRunResult)
    assert any(v.rule_id == "ENT-Q-01" for v in result.violations)
    assert all(v.workflow_state == WorkflowState.OPEN for v in result.violations)


def test_engine_preserves_pending_approval_state():
    snap = _bad_snapshot()
    first = run_engine(snap, existing_violations=[])
    v = first.violations[0]
    v.workflow_state = WorkflowState.PENDING_APPROVAL
    second = run_engine(snap, existing_violations=first.violations)
    matching = [x for x in second.violations
                if x.rule_id == v.rule_id and x.target_id == v.target_id]
    assert len(matching) == 1
    assert matching[0].workflow_state == WorkflowState.PENDING_APPROVAL
    assert matching[0].id == v.id  # same ID preserved


def test_engine_marks_resolved_when_no_longer_violating():
    snap_bad = _bad_snapshot()
    first = run_engine(snap_bad, existing_violations=[])
    # Now data drifts — entitlement description fixed.
    e_clean = make_entitlement(
        id="ENT-1",
        pbl_description="Provides administrator access to the production system for ops users."
    )
    snap_clean = DataSnapshot([e_clean], [], [], [])
    # The previous violation was PENDING_APPROVAL.
    first.violations[0].workflow_state = WorkflowState.PENDING_APPROVAL
    second = run_engine(snap_clean, existing_violations=first.violations)
    resolved = [v for v in second.violations
                if v.workflow_state == WorkflowState.RESOLVED]
    assert len(resolved) == 1


def test_engine_suppresses_re_detection_when_rejected():
    snap = _bad_snapshot()
    first = run_engine(snap, existing_violations=[])
    first.violations[0].workflow_state = WorkflowState.REJECTED
    second = run_engine(snap, existing_violations=first.violations)
    new_open = [v for v in second.violations
                if v.workflow_state == WorkflowState.OPEN
                and v.rule_id == "ENT-Q-01"
                and v.target_id == "ENT-1"]
    assert new_open == []
