"""Native (deterministic) repair regression tests — spec §1 hard invariant.

    generative_operations == 0  =>  external provider calls == 0

A plan with zero generative operations must execute entirely locally and never
touch Genblaze/GMI, while still producing a real repaired artifact, an immutable
version, B2 persistence + read-back hash, validation, and a manifest. The
generative path is separately proven to fail HONESTLY (blocked, never faked)
when a provider is required but unavailable.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings
from rusted_recall.models import Asset, AssetVersion, GenerationRun
from rusted_recall.providers.base import GenerationRequest, GenerationResult
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.storage import get_storage
from tests.support import VISUAL_NEW, VISUAL_OLD


def _img(color=(30, 120, 60), size=(160, 160)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class ExplodingProvider:
    """A provider that FAILS the test if it is ever invoked. Proves the native
    path performs zero provider calls."""

    name = "exploding"
    model = "should-never-run"
    calls = 0

    @property
    def configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        ExplodingProvider.calls += 1
        raise AssertionError("provider was invoked for a zero-generative plan")

    def health_check(self) -> bool:
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'n.db'}")
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'n.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()


def _text_change_company(s, storage):
    """Pure text (claim) change with a crop derivative — a fully deterministic
    reconciliation (no imagery changes)."""
    ws = services.create_workspace(s, "Native Co")
    item, old_v = services.register_source_of_truth(
        s, storage, ws, type="product_package", name="Label", description="truth",
        label="v1", claim_text="24-Hour Vitality", reference_image=_img((200, 40, 40)),
    )
    master, _ = services.ingest_asset(
        s, storage, ws, data=_img((200, 40, 40)), filename="master.png", name="Master",
        asset_type="master", description="hero", declared_source_item_id=item.id,
        on_image_text="24-Hour Vitality",
    )
    services.ingest_asset(
        s, storage, ws, data=_img((200, 40, 40), size=(80, 160)), filename="crop.png",
        name="Crop", asset_type="derivative", description="cropped from master",
        parent_asset_id=master.id, derivation_method="crop",
        # A confirmed declaration makes the crop directly-affected so it is
        # auto-reconciled as a deterministic rebuild from its repaired parent.
        declared_source_item_id=item.id,
    )
    new_v = services.add_source_version(
        s, ws, item, label="v2", claim_text="Daily Botanical Blend",
        storage=storage, reference_image=_img((200, 40, 40)),  # same imagery
    )
    recall = services.create_recall_event(
        s, ws, item=item, old_version=old_v, new_version=new_v, reason="claim update", markets=["US"],
    )
    services.run_impact_analysis(s, ws, recall)
    return ws, recall


def _repaired_versions(s, ws):
    """Repaired versions belonging to THIS workspace only (tests share one DB via
    the cached settings/engine, so global queries would see other tests' rows)."""
    asset_ids = [
        a.id for a in s.execute(
            select(Asset).where(Asset.workspace_id == ws.id)
        ).scalars().all()
    ]
    if not asset_ids:
        return []
    return s.execute(
        select(AssetVersion).where(
            AssetVersion.asset_id.in_(asset_ids),
            AssetVersion.origin == "repaired",
        )
    ).scalars().all()


def test_zero_generative_plan_makes_no_provider_calls(env):
    storage = env
    ExplodingProvider.calls = 0
    with db.session_scope() as s:
        ws, recall = _text_change_company(s, storage)
        # The plan is entirely deterministic.
        assert recall.repair_plan_graph["generative_operations"] == 0
        assert recall.repair_plan_graph["deterministic_rebuilds"] >= 1

        # Wire a provider that explodes if touched.
        pipeline = GenblazePipeline(primary=ExplodingProvider())
        jobs = services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="exploding", model="should-never-run", max_repairs=5,
        )

        # HARD INVARIANT: the provider was never called.
        assert ExplodingProvider.calls == 0
        # Real native repairs completed and the recall is COMPLETED.
        assert jobs and all(j.status == "completed" for j in jobs)
        assert recall.status == recall_fsm.COMPLETED
        # No generative run was recorded for these jobs (native produces none).
        job_ids = [j.id for j in jobs]
        runs = s.execute(
            select(GenerationRun).where(GenerationRun.repair_job_id.in_(job_ids))
        ).scalars().all()
        assert runs == []


def test_native_repair_produces_real_verified_artifact(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _text_change_company(s, storage)
        pipeline = GenblazePipeline(primary=ExplodingProvider())
        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="native", model="deterministic", max_repairs=5,
        )
        repaired = _repaired_versions(s, ws)
        assert repaired
        for v in repaired:
            # Immutable new version with lineage back to its parent.
            assert v.parent_version_id is not None
            assert v.sha256 and v.b2_key and v.manifest_b2_key
            # B2 read-back + hash proof.
            from rusted_recall.hashing import sha256_bytes
            assert sha256_bytes(storage.get_bytes(v.b2_key)) == v.sha256
            # Original preserved (a distinct uploaded version still exists).
            uploaded = s.execute(
                select(AssetVersion).where(
                    AssetVersion.asset_id == v.asset_id, AssetVersion.origin == "uploaded"
                )
            ).scalars().first()
            assert uploaded is not None and uploaded.sha256 != v.sha256


def test_deterministic_rebuild_matches_child_dimensions(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _text_change_company(s, storage)
        pipeline = GenblazePipeline(primary=ExplodingProvider())
        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="native", model="deterministic", max_repairs=5,
        )
        # The crop child (80x160) rebuilt from its repaired parent keeps its dims.
        crop = s.execute(
            select(Asset).where(Asset.workspace_id == ws.id, Asset.name == "Crop")
        ).scalars().first()
        rebuilt = s.execute(
            select(AssetVersion).where(
                AssetVersion.asset_id == crop.id, AssetVersion.origin == "repaired"
            )
        ).scalars().first()
        assert rebuilt is not None
        assert (rebuilt.width, rebuilt.height) == (80, 160)


def test_generative_required_is_blocked_honestly_without_provider(env):
    """A visual change requires generation; with no usable provider it must be
    BLOCKED (failed with a truthful category), never faked as success."""
    storage = env
    with db.session_scope() as s:
        ws = services.create_workspace(s, "Visual Co")
        item, old_v = services.register_source_of_truth(
            s, storage, ws, type="product_package", name="Label", description="truth",
            label="v1", claim_text="same claim", reference_image=VISUAL_OLD,
        )
        services.ingest_asset(
            s, storage, ws, data=VISUAL_OLD, filename="master.png", name="Master",
            asset_type="master", description="hero", declared_source_item_id=item.id,
        )
        new_v = services.add_source_version(
            s, ws, item, label="v2", claim_text="same claim",
            storage=storage, reference_image=VISUAL_NEW,
        )
        recall = services.create_recall_event(
            s, ws, item=item, old_version=old_v, new_version=new_v, reason="art refresh", markets=["US"],
        )
        services.run_impact_analysis(s, ws, recall)
        assert recall.repair_plan_graph["generative_operations"] >= 1

        from rusted_recall.providers.gmicloud import GMICloudProvider
        unconfigured = GMICloudProvider(Settings(gmicloud_api_key=None))
        jobs = services.approve_and_repair(
            s, storage, ws, recall, GenblazePipeline(primary=unconfigured),
            provider_name="gmicloud", model="seedream-5.0-pro", max_repairs=5,
        )
        assert jobs and all(j.status == "failed" for j in jobs)
        # No fake repaired version was created for the blocked generative op.
        assert _repaired_versions(s, ws) == []
        assert recall.status != recall_fsm.COMPLETED
