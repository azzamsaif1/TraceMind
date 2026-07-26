"""Usage metering (spec section 48) and demo cost/quota controls (section 69).

Every metered action writes a real :class:`~rusted_recall.models.UsageEvent`
scoped to organisation + workspace. Account UI reads these rows — nothing is
fabricated.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rusted_recall.models import UsageEvent, Workspace

# Event names (spec section 48).
EVENT_ASSET_UPLOADED = "asset_uploaded"
EVENT_STORAGE_BYTES_ADDED = "storage_bytes_added"
EVENT_ANALYSIS_COMPLETED = "analysis_completed"
EVENT_RECALL_CREATED = "recall_created"
EVENT_GENERATION_OPERATION = "generation_operation"


def record_usage(
    session: Session,
    workspace: Workspace,
    event: str,
    *,
    quantity: float = 1.0,
    operation_id: str | None = None,
    provider_cost: float | None = None,
    detail: dict | None = None,
) -> UsageEvent:
    row = UsageEvent(
        org_id=workspace.org_id,
        workspace_id=workspace.id,
        event=event,
        quantity=quantity,
        operation_id=operation_id,
        provider_cost=provider_cost,
        detail=detail or {},
    )
    session.add(row)
    return row


def usage_summary(session: Session, workspace: Workspace) -> dict[str, float]:
    """Aggregate metered quantities for a workspace."""
    rows = session.execute(
        select(UsageEvent.event, func.sum(UsageEvent.quantity))
        .where(UsageEvent.workspace_id == workspace.id)
        .group_by(UsageEvent.event)
    ).all()
    return {event: float(total or 0.0) for event, total in rows}


def org_usage_summary(session: Session, org_id: str) -> dict[str, float]:
    rows = session.execute(
        select(UsageEvent.event, func.sum(UsageEvent.quantity))
        .where(UsageEvent.org_id == org_id)
        .group_by(UsageEvent.event)
    ).all()
    return {event: float(total or 0.0) for event, total in rows}
