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


def test_completed_is_terminal():
    assert not can_transition(recall.COMPLETED, recall.ANALYSING)


def test_failed_can_reanalyse():
    assert can_transition(recall.FAILED, recall.ANALYSING)


def test_unknown_status_raises():
    with pytest.raises(ValueError):
        can_transition("bogus", recall.DRAFT)
