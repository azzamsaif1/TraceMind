"""Durable repair worker: enqueue de-dup, atomic claim, stale recovery,
restart survival, and end-to-end idempotency (directive section 10 / FINAL
DELIVERY §4, §11, §19.9)."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services, worker
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings, get_settings
from rusted_recall.models import AssetVersion, RepairJob, RepairPlanRow, RepairQueueItem
from rusted_recall.providers import factory
from rusted_recall.providers.base import GenerationRequest, ProviderError
from rusted_recall.storage import get_storage
from tests.support import VISUAL_NEW, VISUAL_OLD, LocalEditProvider


def _img(color=(30, 120, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), color=color).save(buf, format="PNG")
    return buf.getvalue()


class FailingProvider:
    name = "failing"
    model = "m"

    @property
    def configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest):
        raise ProviderError("transient boom", category="provider_unavailable")

    def health_check(self) -> bool:
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'r.db'}")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "store"))
    get_settings.cache_clear()
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'r.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()
    get_settings.cache_clear()


def _setup(s, storage):
    ws = services.create_workspace(s, "Worker WS")
    item, old_v = services.register_source_of_truth(
        s, storage, ws, type="product_package", name="P", description="d",
        label="old", claim_text="old claim", reference_image=VISUAL_OLD,
    )
    new_v = services.add_source_version(
        s, ws, item, label="new", claim_text="new claim",
        storage=storage, reference_image=VISUAL_NEW,
    )
    services.ingest_asset(
        s, storage, ws, data=VISUAL_OLD, filename="a.png", name="A",
        asset_type="master_package", description="d", declared_source_item_id=item.id,
        on_image_text="old claim",
    )
    recall = services.create_recall_event(
        s, ws, item=item, old_version=old_v, new_version=new_v, reason="r", markets=["US"],
    )
    services.run_impact_analysis(s, ws, recall)
    return ws, recall


def test_enqueue_dedups_active_items(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        a = worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
        b = worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
        assert a.id == b.id  # duplicate request -> same durable item
        n = len(s.execute(select(RepairQueueItem)).scalars().all())
        assert n == 1


def test_claim_is_exclusive_and_counts_attempts(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
    # First claim takes the item; second finds nothing queued.
    with db.session_scope() as s:
        item = worker.claim_next(s, "worker-1")
        assert item is not None
        assert item.status == "claimed"
        assert item.attempts == 1
        again = worker.claim_next(s, "worker-2")
        assert again is None


def test_queue_survives_new_process(env):
    """Durability: an item enqueued in one session/'process' is visible after
    the engine is reset (simulating a restart)."""
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
    db.reset_engine()  # simulate web/worker restart
    with db.session_scope() as s:
        items = s.execute(select(RepairQueueItem)).scalars().all()
        assert len(items) == 1 and items[0].status == "queued"


def test_stale_claim_recovered(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
    with db.session_scope() as s:
        item = worker.claim_next(s, "dead-worker")
        item.claimed_at = datetime.now(timezone.utc) - timedelta(hours=1)
    with db.session_scope() as s:
        recovered = worker.recover_stale(s, older_than_seconds=900)
        assert recovered == 1
    with db.session_scope() as s:
        item = s.execute(select(RepairQueueItem)).scalars().first()
        assert item.status == "queued" and item.claimed_by is None


def test_run_once_processes_and_is_idempotent(env, monkeypatch):
    storage = env
    monkeypatch.setattr(factory, "build_primary_provider", lambda settings=None: LocalEditProvider())
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        recall_id = recall.id
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)

    assert worker.run_once("w1") is True
    assert worker.run_once("w1") is False  # queue drained

    with db.session_scope() as s:
        from rusted_recall.models import RecallEvent
        r = s.get(RecallEvent, recall_id)
        assert r.status == recall_fsm.COMPLETED
        before = (
            len(s.execute(select(AssetVersion).where(AssetVersion.origin == "repaired")).scalars().all()),
            len(s.execute(select(RepairPlanRow)).scalars().all()),
            len(s.execute(select(RepairJob)).scalars().all()),
        )

    # Re-enqueue + re-run: terminal recall -> no duplicate versions/plans/jobs.
    with db.session_scope() as s:
        from rusted_recall.models import Workspace
        ws = s.execute(select(Workspace)).scalars().first()
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall_id)
    worker.run_once("w1")
    with db.session_scope() as s:
        after = (
            len(s.execute(select(AssetVersion).where(AssetVersion.origin == "repaired")).scalars().all()),
            len(s.execute(select(RepairPlanRow)).scalars().all()),
            len(s.execute(select(RepairJob)).scalars().all()),
        )
    assert after == before


def test_run_once_provider_failure_is_honest(env, monkeypatch):
    """Provider failure must not raise out of the worker; recall stays
    partially_completed (never fake COMPLETED)."""
    storage = env
    monkeypatch.setattr(factory, "build_primary_provider", lambda settings=None: FailingProvider())
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        recall_id = recall.id
        worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)

    assert worker.run_once("w1") is True
    with db.session_scope() as s:
        from rusted_recall.models import RecallEvent
        r = s.get(RecallEvent, recall_id)
        assert r.status == recall_fsm.PARTIALLY_COMPLETED
        item = s.execute(select(RepairQueueItem)).scalars().first()
        assert item.status == "done"  # attempted; user retry enqueues a fresh item
