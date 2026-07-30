"""Separate durable repair worker (directive section 10 / FINAL DELIVERY §4).

Production topology:

    WEB  --enqueue-->  repair_queue_items (DB)  --claim-->  WORKER

The web process only *persists* a task; a distinct worker process claims and
executes it. Because the task lives in the database (not an in-memory queue),
work survives a web or worker restart, duplicate requests are de-duplicated,
and a claim abandoned by a crashed worker is recovered.

The unit of work is a whole recall executed via ``services.approve_and_repair``,
which is itself idempotent (retry-failed-only, sticky-completed, terminal no-op).
So re-running a claimed-but-crashed item can never create duplicate versions,
manifests, jobs, or provider charges.

Run the worker as its own process:

    python -m rusted_recall.worker
"""
from __future__ import annotations

import os
import signal
import socket
import time
from datetime import datetime, timedelta, timezone
from types import FrameType

from sqlalchemy import func, select

from rusted_recall import services
from rusted_recall.config import Settings, get_settings
from rusted_recall.db import session_scope
from rusted_recall.logging_setup import configure_logging, get_logger, log_context
from rusted_recall.models import RecallEvent, RepairQueueItem, Workspace
from rusted_recall.storage import get_storage

logger = get_logger(__name__)

QUEUED = "queued"
CLAIMED = "claimed"
DONE = "done"
FAILED = "failed"
ACTIVE = (QUEUED, CLAIMED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def enqueue_repair(
    session,
    *,
    workspace_id: str,
    recall_id: str,
    asset_ids: list[str] | None = None,
    max_attempts: int = 3,
) -> RepairQueueItem:
    """Persist a repair task. De-duplicates: if an active (queued/claimed) item
    already exists for the recall, return it instead of creating a duplicate.
    This is what makes a double-clicked "Repair" button safe at the boundary."""
    existing = session.execute(
        select(RepairQueueItem)
        .where(
            RepairQueueItem.recall_event_id == recall_id,
            RepairQueueItem.status.in_(ACTIVE),
        )
        .order_by(RepairQueueItem.created_at)
    ).scalars().first()
    if existing is not None:
        return existing
    item = RepairQueueItem(
        workspace_id=workspace_id,
        recall_event_id=recall_id,
        asset_ids=asset_ids,
        status=QUEUED,
        max_attempts=max_attempts,
    )
    session.add(item)
    session.flush()
    logger.info("repair task enqueued", extra={"recall_id": recall_id, "queue_item_id": item.id})
    return item


def claim_next(session, worker_id: str) -> RepairQueueItem | None:
    """Atomically claim the oldest queued item. On PostgreSQL uses
    ``FOR UPDATE SKIP LOCKED`` so concurrent workers never claim the same row;
    on SQLite (single-writer) the surrounding transaction is sufficient."""
    is_postgres = session.bind.dialect.name == "postgresql"
    stmt = (
        select(RepairQueueItem)
        .where(RepairQueueItem.status == QUEUED)
        .order_by(RepairQueueItem.created_at)
        .limit(1)
    )
    if is_postgres:
        stmt = stmt.with_for_update(skip_locked=True)
    item = session.execute(stmt).scalars().first()
    if item is None:
        return None
    item.status = CLAIMED
    item.claimed_by = worker_id
    item.claimed_at = _now()
    item.attempts += 1
    session.flush()
    return item


def recover_stale(session, *, older_than_seconds: float) -> int:
    """Requeue (or fail) items claimed longer ago than the timeout — recovers
    work abandoned by a crashed/restarted worker."""
    cutoff = _now() - timedelta(seconds=older_than_seconds)
    stale = session.execute(
        select(RepairQueueItem).where(
            RepairQueueItem.status == CLAIMED,
            RepairQueueItem.claimed_at.is_not(None),
            RepairQueueItem.claimed_at < cutoff,
        )
    ).scalars().all()
    for item in stale:
        if item.attempts >= item.max_attempts:
            item.status = FAILED
            item.last_error = "stale claim exceeded max attempts"
            logger.warning("stale queue item failed", extra={"queue_item_id": item.id})
        else:
            item.status = QUEUED
            item.claimed_by = None
            item.claimed_at = None
            logger.warning("stale queue item requeued", extra={"queue_item_id": item.id})
    return len(stale)


def process_item(item_id: str, settings: Settings | None = None) -> None:
    """Execute a claimed item's recall repair. Marks the item done on success.
    Provider failures do NOT raise here — ``approve_and_repair`` records them as
    failed jobs and leaves the recall partially_completed (honest state); the
    item is still 'done' (attempted) and a user retry enqueues a fresh item."""
    settings = settings or get_settings()
    storage = get_storage(settings)
    from rusted_recall.providers.factory import build_primary_provider
    from rusted_recall.providers.genblaze import GenblazePipeline

    pipeline = GenblazePipeline(primary=build_primary_provider(settings), settings=settings)

    with session_scope() as session:
        item = session.get(RepairQueueItem, item_id)
        if item is None:
            return
        recall = session.get(RecallEvent, item.recall_event_id)
        workspace = session.get(Workspace, item.workspace_id)
        if recall is None or workspace is None:
            item.status = FAILED
            item.last_error = "recall or workspace no longer exists"
            return
        with log_context(recall_id=recall.id, workspace_id=workspace.id, queue_item_id=item.id):
            services.approve_and_repair(
                session, storage, workspace, recall, pipeline,
                provider_name="gmicloud",
                model=settings.gmicloud_model,
                asset_ids=item.asset_ids,
                max_repairs=settings.demo_max_repairs_per_recall,
            )
            item.status = DONE
            item.last_error = ""


def run_once(worker_id: str, settings: Settings | None = None) -> bool:
    """Claim and process a single item. Returns True if an item was handled."""
    with session_scope() as session:
        item = claim_next(session, worker_id)
        item_id = item.id if item is not None else None
    if item_id is None:
        return False
    try:
        process_item(item_id, settings)
    except Exception as exc:  # noqa: BLE001 - durable worker must not die on one item
        logger.exception("repair item processing failed", extra={"queue_item_id": item_id})
        with session_scope() as session:
            item = session.get(RepairQueueItem, item_id)
            if item is not None:
                item.last_error = str(exc)[:2000]
                if item.attempts >= item.max_attempts:
                    item.status = FAILED
                else:
                    item.status = QUEUED
                    item.claimed_by = None
                    item.claimed_at = None
    return True


def queue_depth(session) -> dict[str, int]:
    rows = session.execute(
        select(RepairQueueItem.status, func.count()).group_by(RepairQueueItem.status)
    ).all()
    depth = {QUEUED: 0, CLAIMED: 0, DONE: 0, FAILED: 0}
    for status, count in rows:
        depth[status] = count
    return depth


class _Stop:
    def __init__(self) -> None:
        self.stop = False

    def request(self, signum: int, frame: FrameType | None) -> None:
        self.stop = True


def run_forever(
    *,
    poll_interval: float = 2.0,
    stale_after_seconds: float = 900.0,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    worker_id = worker_identity()
    stopper = _Stop()
    signal.signal(signal.SIGTERM, stopper.request)
    signal.signal(signal.SIGINT, stopper.request)
    logger.info("repair worker started", extra={"worker_id": worker_id})
    last_recover = 0.0
    while not stopper.stop:
        now = time.monotonic()
        if now - last_recover > stale_after_seconds / 3:
            with session_scope() as session:
                recover_stale(session, older_than_seconds=stale_after_seconds)
            last_recover = now
        worked = run_once(worker_id, settings)
        if not worked:
            time.sleep(poll_interval)
    logger.info("repair worker stopped", extra={"worker_id": worker_id})


def main() -> None:
    configure_logging()
    run_forever()


if __name__ == "__main__":
    main()
