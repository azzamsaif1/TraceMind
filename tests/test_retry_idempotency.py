"""Retry-failed-only, FSM partially_completed->repairing retry, and idempotency
(directive sections: FIX RECALL FSM, RETRY FAILED ONLY, IDEMPOTENCY)."""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings
from rusted_recall.models import AssetVersion, RepairJob, RepairPlanRow
from rusted_recall.providers.base import GenerationRequest, ProviderError
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.storage import get_storage
from tests.support import LocalEditProvider


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
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'r.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()


def _setup(s, storage):
    ws = services.create_workspace(s, "Retry WS")
    item, old_v = services.register_source_of_truth(
        s, storage, ws, type="product_package", name="P", description="d",
        label="old", claim_text="old claim", reference_image=_img(),
    )
    new_v = services.add_source_version(
        s, ws, item, label="new", claim_text="new claim",
        storage=storage, reference_image=_img((60, 160, 90)),
    )
    services.ingest_asset(
        s, storage, ws, data=_img(), filename="a.png", name="A",
        asset_type="master_package", description="d", declared_source_item_id=item.id,
        on_image_text="old claim",
    )
    recall = services.create_recall_event(
        s, ws, item=item, old_version=old_v, new_version=new_v, reason="r", markets=["US"],
    )
    services.run_impact_analysis(s, ws, recall)
    return ws, recall


def test_retry_failed_only_and_fsm(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)

        # First attempt fails at the provider.
        jobs = services.approve_and_repair(
            s, storage, ws, recall, GenblazePipeline(primary=FailingProvider()),
            provider_name="failing", model="m", max_repairs=3,
        )
        assert jobs and all(j.status == "failed" for j in jobs)
        assert recall.status == recall_fsm.PARTIALLY_COMPLETED

        # Retry with a working provider: FSM must go partially_completed->repairing
        # (no IllegalTransitionError) and the failed asset is retried to success.
        jobs2 = services.approve_and_repair(
            s, storage, ws, recall, GenblazePipeline(primary=LocalEditProvider()),
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )
        assert jobs2 and all(j.status in ("completed", "requires_review") for j in jobs2)
        assert recall.status == recall_fsm.COMPLETED


def test_idempotent_repeated_repair(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _setup(s, storage)
        pipeline = GenblazePipeline(primary=LocalEditProvider())

        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )

        def counts():
            v = len(s.execute(select(AssetVersion).where(AssetVersion.origin == "repaired")).scalars().all())
            p = len(s.execute(select(RepairPlanRow)).scalars().all())
            j = len(s.execute(select(RepairJob)).scalars().all())
            return v, p, j

        before = counts()
        # Repeated clicks must not create duplicate versions/plans/jobs.
        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )
        assert counts() == before
