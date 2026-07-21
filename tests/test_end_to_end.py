"""End-to-end vertical slice through the production services (directive section 29):
upload -> store -> connect to source -> create recall -> classify impact ->
repair through the pipeline -> store new version -> show lineage.

Uses SQLite + local storage + a deterministic test provider (test-only).
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from rusted_recall import db, services
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings
from rusted_recall.models import AssetVersion
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.storage import get_storage
from tests.support import LocalEditProvider


def _img(color, size=(256, 256), text=None):
    img = Image.new("RGB", size, color=color)
    if text:
        ImageDraw.Draw(img).text((10, 10), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'e2e.db'}")
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local", local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'e2e.db'}",
    )
    storage = get_storage(settings)
    yield storage
    db.reset_engine()


def test_full_recall_slice(env):
    storage = env
    old_pkg = _img((30, 120, 60), text="24-Hour Vitality")
    new_pkg = _img((60, 160, 90), text="Daily Botanical Blend")

    with db.session_scope() as s:
        ws = services.create_workspace(s, "LumaLeaf Demo")

        item, old_v = services.register_source_of_truth(
            s, storage, ws,
            type="product_package", name="LumaLeaf Botanical Sparkling Water",
            description="LumaLeaf botanical sparkling water product package",
            label="24-Hour Vitality", claim_text="24-Hour Vitality",
            reference_image=old_pkg,
        )
        new_v = services.add_source_version(
            s, ws, item, label="Daily Botanical Blend", claim_text="Daily Botanical Blend",
            storage=storage, reference_image=new_pkg,
        )

        # explicit-declared hero ad
        hero, _ = services.ingest_asset(
            s, storage, ws, data=_img((30, 120, 60), text="24-Hour Vitality hero"),
            filename="hero.png", name="Hero Ad", asset_type="hero_ad",
            description="LumaLeaf botanical sparkling water hero advertisement",
            declared_source_item_id=item.id, on_image_text="24-Hour Vitality",
            publication_status="published",
        )
        # exact duplicate of the old package
        services.ingest_asset(
            s, storage, ws, data=old_pkg, filename="dup.png", name="Master Package",
            asset_type="master_package", description="LumaLeaf master package",
            on_image_text="24-Hour Vitality",
        )
        # perceptual derivative (crop child of hero)
        services.ingest_asset(
            s, storage, ws, data=_img((30, 120, 61), text="24-Hour Vitality hero"),
            filename="crop.png", name="Hero Crop", asset_type="derived_crop",
            description="cropped hero", parent_asset_id=hero.id, on_image_text="24-Hour Vitality",
        )
        # safe unrelated asset
        services.ingest_asset(
            s, storage, ws, data=_img((200, 30, 30), text="unrelated"),
            filename="safe.png", name="Unrelated Poster", asset_type="other",
            description="completely different subject",
        )

        recall = services.create_recall_event(
            s, ws, item=item, old_version=old_v, new_version=new_v,
            reason="Claim change: 24-Hour Vitality -> Daily Botanical Blend",
            markets=["US"],
        )
        services.run_impact_analysis(s, ws, recall)
        assert recall.status == recall_fsm.READY_FOR_REVIEW

        classifications = {i.asset_id: i.classification for i in recall.impacts}
        # explicit-declared hero must be directly affected
        assert classifications[hero.id] == "directly_affected"
        # at least one safe asset exists
        assert "safe" in classifications.values()

        pipeline = GenblazePipeline(primary=LocalEditProvider())
        jobs = services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )
        assert jobs, "expected at least one repair job"
        completed = [j for j in jobs if j.status in ("completed", "requires_review")]
        assert completed, "expected repairs to execute"

        # immutability + lineage: repaired version references its parent, original intact
        for job in completed:
            new_version = s.get(AssetVersion, job.result_version_id)
            assert new_version.origin == "repaired"
            assert new_version.parent_version_id is not None
            parent = s.get(AssetVersion, new_version.parent_version_id)
            assert parent.origin == "uploaded"
            assert parent.sha256 != new_version.sha256  # output differs
            assert storage.exists(parent.b2_key)  # original preserved
            assert storage.exists(new_version.b2_key)  # new stored
            assert new_version.manifest_b2_key and storage.exists(new_version.manifest_b2_key)

        report = services.build_report(s, ws, recall, elapsed_seconds=1.0)
        d = report.as_dict()
        assert d["totals"]["total_assets_scanned"] == 4
        assert d["totals"]["repair_requested"] >= 1
        assert d["operations"]["b2_objects_created"] > 0


def test_repair_disabled_without_provider(env):
    """Without a configured provider the pipeline is disabled — no fake output."""
    storage = env
    with db.session_scope() as s:
        ws = services.create_workspace(s, "NoProvider")
        item, old_v = services.register_source_of_truth(
            s, storage, ws, type="product_package", name="P", description="d",
            label="old", claim_text="old claim", reference_image=_img((1, 2, 3)),
        )
        new_v = services.add_source_version(
            s, ws, item, label="new", claim_text="new claim",
            storage=storage, reference_image=_img((4, 5, 6)),
        )
        services.ingest_asset(
            s, storage, ws, data=_img((1, 2, 3)), filename="a.png", name="A",
            asset_type="master_package", description="d", declared_source_item_id=item.id,
        )
        recall = services.create_recall_event(
            s, ws, item=item, old_version=old_v, new_version=new_v, reason="r", markets=["US"],
        )
        services.run_impact_analysis(s, ws, recall)

        from rusted_recall.providers.gmicloud import GMICloudProvider

        pipeline = GenblazePipeline(primary=GMICloudProvider(Settings(gmicloud_api_key=None)))
        jobs = services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="gmicloud", model="m", max_repairs=1,
        )
        assert jobs
        assert all(j.status == "failed" and j.error_category == "authentication" for j in jobs)
