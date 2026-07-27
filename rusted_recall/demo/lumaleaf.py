"""LumaLeaf Botanical Sparkling Water demo dataset (directive sections 6, 21).

Images are generated procedurally (no third-party assets) so provenance is
clean. The seed drives the SAME production services used by the web app — it
never inserts graph/impact rows directly.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from rusted_recall import services
from rusted_recall.config import Settings, get_settings
from rusted_recall.db import create_all, session_scope
from rusted_recall.storage import get_storage

OLD_CLAIM = "24-Hour Vitality"
NEW_CLAIM = "Daily Botanical Blend"
BRAND = "LumaLeaf"
SLUG = "lumaleaf-botanical"

# Palette per asset so previews are visually distinct but derived from the pack.
_BASE = (34, 120, 66)


def _canvas(size, base=_BASE, claim=OLD_CLAIM, subtitle="", accent=(212, 175, 55)):
    img = Image.new("RGB", size, base)
    d = ImageDraw.Draw(img)
    w, h = size
    d.rectangle([0, 0, w, 46], fill=(20, 74, 41))
    d.text((14, 15), f"{BRAND} Botanical Sparkling Water", fill=(240, 240, 230))
    # "bottle"
    d.rounded_rectangle([w // 2 - 34, 70, w // 2 + 34, h - 80], radius=18, fill=(18, 92, 52), outline=accent, width=3)
    d.text((w // 2 - 30, h // 2 - 10), BRAND, fill=(245, 245, 235))
    d.rectangle([0, h - 60, w, h], fill=(16, 60, 34))
    d.text((14, h - 44), claim, fill=accent)
    if subtitle:
        d.text((14, h - 26), subtitle, fill=(210, 210, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    create_all()
    storage = get_storage(settings)

    old_pkg = _canvas((420, 560), claim=OLD_CLAIM, subtitle="Net 330ml")
    new_pkg = _canvas((420, 560), base=(30, 132, 74), claim=NEW_CLAIM, subtitle="Net 330ml", accent=(233, 196, 106))

    with session_scope() as session:
        if services.get_workspace_by_slug(session, "lumaleaf-botanical"):
            return {"status": "already_seeded"}

        ws = services.create_workspace(session, "LumaLeaf Botanical")

        item, old_v = services.register_source_of_truth(
            session, storage, ws,
            type="product_package",
            name="LumaLeaf Botanical Sparkling Water — 330ml can",
            description="LumaLeaf botanical sparkling water primary product package and on-pack claim",
            label=OLD_CLAIM, claim_text=OLD_CLAIM,
            reference_image=old_pkg, region="US",
            tags=["package", "primary-claim"],
        )
        new_v = services.add_source_version(
            session, ws, item, label=NEW_CLAIM, claim_text=NEW_CLAIM,
            storage=storage, reference_image=new_pkg,
        )

        # Campaign assets — same production ingestion path.
        master, _ = services.ingest_asset(
            session, storage, ws, data=old_pkg, filename="master-pack.png",
            name="Master Pack Render", asset_type="master_package",
            campaign="LumaLeaf Launch", description="LumaLeaf master package render, primary claim on pack",
            declared_source_item_id=item.id, on_image_text=OLD_CLAIM, publication_status="published",
        )
        hero, _ = services.ingest_asset(
            session, storage, ws,
            data=_canvas((640, 400), claim=OLD_CLAIM, subtitle="Feel the 24-Hour Vitality"),
            filename="hero-ad.png", name="Hero Advertisement", asset_type="hero_ad",
            campaign="LumaLeaf Launch",
            description="LumaLeaf botanical sparkling water hero advertisement with on-pack claim",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((400, 400), claim=OLD_CLAIM, subtitle="#StayVital"),
            filename="social-square.png", name="Square Social Post", asset_type="square_social",
            campaign="LumaLeaf Launch",
            description="LumaLeaf square social post featuring the product and claim",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # perceptual derivative / crop child of the hero
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((642, 402), claim=OLD_CLAIM, subtitle="Feel the 24-Hour Vitality"),
            filename="hero-crop.png", name="Hero Crop (email header)", asset_type="email_header",
            campaign="LumaLeaf Launch", description="cropped hero variant for email header",
            parent_asset_id=hero.id, derivation_method="crop",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # story format with the claim
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((360, 640), claim=OLD_CLAIM, subtitle="Swipe up"),
            filename="story.png", name="Vertical Story", asset_type="story",
            campaign="LumaLeaf Launch", description="vertical story ad with product package and claim",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # unrelated safe asset (different brand/subject)
        services.ingest_asset(
            session, storage, ws,
            data=_recruiting_poster(),
            filename="hiring.png", name="We're Hiring Poster", asset_type="other",
            campaign="Corporate", description="corporate recruiting poster, unrelated to the product",
            publication_status="draft",
        )

        recall = services.create_recall_event(
            session, ws, item=item, old_version=old_v, new_version=new_v,
            reason=f"Regulatory claim change: “{OLD_CLAIM}” → “{NEW_CLAIM}”",
            severity="high", markets=["US"],
        )
        services.run_impact_analysis(session, ws, recall)
        return {
            "status": "seeded",
            "workspace": ws.slug,
            "recall_id": recall.id,
            "master_asset": master.id,
        }


def _recruiting_poster() -> bytes:
    img = Image.new("RGB", (400, 500), (40, 44, 60))
    d = ImageDraw.Draw(img)
    d.text((20, 30), "WE'RE HIRING", fill=(255, 255, 255))
    d.text((20, 70), "Join the LumaLeaf corporate team", fill=(180, 190, 210))
    d.rectangle([20, 120, 380, 460], outline=(90, 100, 130), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    import json

    print(json.dumps(seed(), indent=2))
