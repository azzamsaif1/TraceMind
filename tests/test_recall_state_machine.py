import pytest

from rusted_recall import recall
from rusted_recall.recall import IllegalTransitionError, can_transition, is_terminal, transition


def test_happy_path():
    status = recall.DRAFT
    for target in [
        recall.ANALYSING,
        recall.READY_FOR_REVIEW,
        recall.APPROVED,
        recall.REPAIRING,
        recall.COMPLETED,
    ]:
        status = transition(status, target)
    assert status == recall.COMPLETED
    assert is_terminal(status)


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransitionError):
        transition(recall.DRAFT, recall.COMPLETED)


def test_partial_then_complete():
    assert can_transition(recall.REPAIRING, recall.PARTIALLY_COMPLETED)
    assert can_transition(recall.PARTIALLY_COMPLETED, recall.COMPLETED)


def test_partial_can_retry_via_repairing():
    # Retry path: a partially_completed recall must be able to go back to
    # repairing (this is what lets retry-failed-only re-derive the final state).
    assert can_transition(recall.PARTIALLY_COMPLETED, recall.REPAIRING)


def test_no_illegal_same_state_partial_transition():
    # Regression for IllegalTransitionError partially_completed->partially_completed.
    assert not can_transition(recall.PARTIALLY_COMPLETED, recall.PARTIALLY_COMPLETED)
    with pytest.raises(IllegalTransitionError):
        transition(recall.PARTIALLY_COMPLETED, recall.PARTIALLY_COMPLETED)


def test_completed_is_terminal():
    assert not can_transition(recall.COMPLETED, recall.ANALYSING)


def test_failed_can_reanalyse():
    assert can_transition(recall.FAILED, recall.ANALYSING)


def test_unknown_status_raises():
    with pytest.raises(ValueError):
        can_transition("bogus", recall.DRAFT)
