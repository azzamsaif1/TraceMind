"""Integration: ChangeSet + Minimal Repair Plan persistence and usage metering
run through the real production services (no direct row insertion)."""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from rusted_recall import auth, db, services, usage
from rusted_recall.config import Settings
from rusted_recall.storage import get_storage


def _img(color, size=(256, 256), text=None):
    img = Image.new("RGB", size, color=color)
    if text:
        ImageDraw.Draw(img).text((10, 10), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'u.db'}")
    db.reset_engine()
    db.create_all()
    settings = Settings(
        storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'u.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()


def test_changeset_plan_and_usage_recorded(storage):
    with db.session_scope() as s:
        _, org = auth.sign_up(s, email="w@example.com", password="password123", org_name="W")
        ws = services.create_workspace(s, "WS", org_id=org.id)

        item, old_v = services.register_source_of_truth(
            s, storage, ws, type="product_package", name="LumaLeaf",
            description="botanical sparkling water package",
            label="24-Hour Vitality", claim_text="24-Hour Vitality",
            reference_image=_img((30, 120, 60), text="24-Hour Vitality"),
        )
        new_v = services.add_source_version(
            s, ws, item, label="Daily Botanical Blend", claim_text="Daily Botanical Blend",
            storage=storage, reference_image=_img((60, 160, 90), text="Daily Botanical Blend"),
        )
        master, _ = services.ingest_asset(
            s, storage, ws, data=_img((30, 120, 60), text="24-Hour Vitality"),
            filename="master.png", name="Master", asset_type="master_package",
            description="master package", declared_source_item_id=item.id,
            on_image_text="24-Hour Vitality", publication_status="published",
        )
        # deterministic crop child of the master
        services.ingest_asset(
            s, storage, ws, data=_img((30, 120, 61), text="24-Hour Vitality"),
            filename="crop.png", name="Hero Crop", asset_type="derived_crop",
            description="cropped master", parent_asset_id=master.id,
            derivation_method="crop", on_image_text="24-Hour Vitality",
            publication_status="published",
        )

        recall = services.create_recall_event(
            s, ws, item=item, old_version=old_v, new_version=new_v,
            reason="claim change", markets=["US"],
        )
        # ChangeSet auto-proposed and persisted
        assert recall.changeset["operations"]
        assert any(op["type"] == "replace_text" for op in recall.changeset["operations"])

        services.run_impact_analysis(s, ws, recall)

        # Minimal repair plan persisted with calculated savings
        plan = recall.repair_plan_graph
        assert plan["naive_generative_operations"] >= 1
        assert "operations_avoided" in plan
        assert plan["operations_avoided"] >= 0

        # propagation outputs persisted on impacts
        impacts = {i.asset_id: i for i in recall.impacts}
        assert impacts[master.id].causal_explanation
        assert impacts[master.id].propagation_reason

        # usage metered through real events
        summary = usage.usage_summary(s, ws)
        assert summary.get("asset_uploaded") == 2
        assert summary.get("recall_created") == 1
        assert usage.org_usage_summary(s, org.id).get("asset_uploaded") == 2
