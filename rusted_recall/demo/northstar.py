"""Northstar Coffee generalisation dataset (directive section 11).

This is a *second, unrelated* campaign whose only purpose is to prove that the
ChangePropagationEngine and MinimalRepairPlanner generalise: it reuses NONE of
the LumaLeaf strings, IDs, filenames, topology or fixture relationships. It is
seeded through the SAME production services (never inserting graph/impact rows
directly), so a passing generalisation recall is evidence that impact analysis
and repair planning are genuine algorithms rather than demo-specific logic.

Topology (deliberately different from LumaLeaf's master -> hero -> crop shape):

    Package v1 (source of truth)
        -> Packaging Master              (explicit declaration)
             -> Website Banner           (parent-child derivation)
                  -> Banner Mobile Crop  (deterministic crop child)
                  -> Banner Desktop Wide (deterministic resize child)
        Menu Card                        (independent claim-bearing asset)
        Office Wi-Fi Notice              (disconnected -> must stay safe)
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from rusted_recall import services
from rusted_recall.config import Settings, get_settings
from rusted_recall.db import create_all, session_scope
from rusted_recall.storage import get_storage

OLD_CLAIM = "Single-Origin Colombian Roast"
NEW_CLAIM = "Seasonal House Roast"
BRAND = "Northstar Coffee"
SLUG = "northstar-coffee"

_BASE = (60, 38, 24)


def _canvas(size, base=_BASE, claim=OLD_CLAIM, subtitle="", accent=(212, 160, 92)):
    img = Image.new("RGB", size, base)
    d = ImageDraw.Draw(img)
    w, h = size
    d.rectangle([0, 0, w, 46], fill=(38, 24, 15))
    d.text((14, 15), f"{BRAND} Roasters", fill=(236, 224, 208))
    # coffee "bag"
    d.rounded_rectangle([w // 2 - 38, 70, w // 2 + 38, h - 80], radius=10, fill=(30, 20, 13), outline=accent, width=3)
    d.text((w // 2 - 26, h // 2 - 10), BRAND, fill=(240, 228, 210))
    d.rectangle([0, h - 60, w, h], fill=(34, 22, 14))
    d.text((14, h - 44), claim, fill=accent)
    if subtitle:
        d.text((14, h - 26), subtitle, fill=(206, 190, 170))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    create_all()
    storage = get_storage(settings)

    old_pkg = _canvas((420, 560), claim=OLD_CLAIM, subtitle="Whole Bean 340g")
    new_pkg = _canvas((420, 560), base=(72, 46, 28), claim=NEW_CLAIM, subtitle="Whole Bean 340g", accent=(224, 176, 108))

    with session_scope() as session:
        if services.get_workspace_by_slug(session, SLUG):
            return {"status": "already_seeded"}

        ws = services.create_workspace(session, "Northstar Coffee")

        item, old_v = services.register_source_of_truth(
            session, storage, ws,
            type="product_package",
            name="Northstar Coffee — 340g whole-bean bag",
            description="Northstar Coffee primary retail bag artwork and on-pack roast claim",
            label=OLD_CLAIM, claim_text=OLD_CLAIM,
            reference_image=old_pkg, region="US",
            tags=["package", "roast-claim"],
        )
        new_v = services.add_source_version(
            session, ws, item, label=NEW_CLAIM, claim_text=NEW_CLAIM,
            storage=storage, reference_image=new_pkg,
        )

        # Packaging master declares the source of truth.
        master, _ = services.ingest_asset(
            session, storage, ws, data=old_pkg, filename="packaging-master.png",
            name="Packaging Master", asset_type="master_package",
            campaign="Northstar Retail", description="Northstar packaging master render with on-pack roast claim",
            declared_source_item_id=item.id, on_image_text=OLD_CLAIM, publication_status="published",
        )
        # Website banner is derived from the master (one hop deeper than LumaLeaf's hero).
        banner, _ = services.ingest_asset(
            session, storage, ws,
            data=_canvas((900, 300), claim=OLD_CLAIM, subtitle="Shop the roast"),
            filename="website-banner.png", name="Website Banner", asset_type="web_banner",
            campaign="Northstar Retail", description="homepage hero banner derived from packaging master",
            parent_asset_id=master.id, derivation_method="composite",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # Two deterministic children of the banner -> planner should rebuild, not regenerate.
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((450, 300), claim=OLD_CLAIM, subtitle="Shop the roast"),
            filename="banner-mobile.png", name="Banner Mobile Crop", asset_type="web_banner",
            campaign="Northstar Retail", description="mobile crop of the website banner",
            parent_asset_id=banner.id, derivation_method="crop",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((1200, 300), claim=OLD_CLAIM, subtitle="Shop the roast"),
            filename="banner-desktop.png", name="Banner Desktop Wide", asset_type="web_banner",
            campaign="Northstar Retail", description="wide desktop resize of the website banner",
            parent_asset_id=banner.id, derivation_method="resize",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # Independent claim-bearing asset (no lineage edge; text/visual evidence only).
        services.ingest_asset(
            session, storage, ws,
            data=_canvas((500, 700), claim=OLD_CLAIM, subtitle="Cafe menu"),
            filename="menu-card.png", name="Cafe Menu Card", asset_type="print",
            campaign="Northstar Retail", description="in-cafe menu card printing the roast claim",
            on_image_text=OLD_CLAIM, publication_status="published",
        )
        # Disconnected, unrelated asset -> must remain safe.
        services.ingest_asset(
            session, storage, ws,
            data=_wifi_notice(),
            filename="wifi-notice.png", name="Office Wi-Fi Notice", asset_type="other",
            campaign="Operations", description="internal office wifi notice, unrelated to product",
            publication_status="draft",
        )

        recall = services.create_recall_event(
            session, ws, item=item, old_version=old_v, new_version=new_v,
            reason=f"Seasonal roast change: “{OLD_CLAIM}” → “{NEW_CLAIM}”",
            severity="high", markets=["US"],
        )
        services.run_impact_analysis(session, ws, recall)
        return {
            "status": "seeded",
            "workspace": ws.slug,
            "recall_id": recall.id,
            "master_asset": master.id,
        }


def _wifi_notice() -> bytes:
    img = Image.new("RGB", (400, 300), (28, 40, 52))
    d = ImageDraw.Draw(img)
    d.text((20, 30), "OFFICE WI-FI", fill=(255, 255, 255))
    d.text((20, 70), "Network: Northstar-Guest", fill=(180, 200, 220))
    d.rectangle([20, 110, 380, 260], outline=(80, 110, 140), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    import json

    print(json.dumps(seed(), indent=2))
