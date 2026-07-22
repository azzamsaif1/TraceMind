"""Recall-event state machine (directive section 5).

Every status transition is validated; illegal transitions raise. The exact
statuses required by the directive are used verbatim.
"""
from __future__ import annotations

DRAFT = "draft"
ANALYSING = "analysing"
READY_FOR_REVIEW = "ready_for_review"
APPROVED = "approved"
REPAIRING = "repairing"
PARTIALLY_COMPLETED = "partially_completed"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

STATUSES = (
    DRAFT,
    ANALYSING,
    READY_FOR_REVIEW,
    APPROVED,
    REPAIRING,
    PARTIALLY_COMPLETED,
    COMPLETED,
    FAILED,
    CANCELLED,
)

# Allowed transitions between statuses.
_TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {ANALYSING, CANCELLED},
    ANALYSING: {READY_FOR_REVIEW, FAILED, CANCELLED},
    READY_FOR_REVIEW: {APPROVED, ANALYSING, CANCELLED},
    APPROVED: {REPAIRING, CANCELLED},
    REPAIRING: {PARTIALLY_COMPLETED, COMPLETED, FAILED},
    PARTIALLY_COMPLETED: {REPAIRING, COMPLETED, CANCELLED},
    COMPLETED: set(),
    FAILED: {ANALYSING, CANCELLED},
    CANCELLED: set(),
}

TERMINAL = {COMPLETED, CANCELLED}


class IllegalTransitionError(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    if current not in _TRANSITIONS:
        raise ValueError(f"unknown status: {current}")
    if target not in STATUSES:
        raise ValueError(f"unknown status: {target}")
    return target in _TRANSITIONS[current]


def transition(current: str, target: str) -> str:
    if not can_transition(current, target):
        raise IllegalTransitionError(f"cannot move recall from '{current}' to '{target}'")
    return target


def is_terminal(status: str) -> bool:
    return status in TERMINAL
