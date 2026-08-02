"""New-company self-onboarding through the deployed product UI (spec sections
12, 19.4, 19.5). A brand-new company must be able to create truth, register
assets, declare dependencies, and run a Recall with NO seed script, NO SQL, and
NO source-code change — and must never see another company's data.
"""
from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _png(color: tuple[int, int, int], size: tuple[int, int] = (128, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'web.db'}")

    import rusted_recall.config as config

    config.get_settings.cache_clear()
    from rusted_recall import db

    db.reset_engine()
    import rusted_recall.web.app as webapp

    importlib.reload(webapp)
    db.create_all()
    with TestClient(webapp.app) as c:
        yield c
    db.reset_engine()
    config.get_settings.cache_clear()


def _signup(client: TestClient, email: str, org: str) -> None:
    client.cookies.clear()
    r = client.post(
        "/signup",
        data={"email": email, "password": "password123", "org_name": org},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def _onboard_company(client: TestClient) -> str:
    """Create SoT + two assets through the UI. Returns the source item id."""
    # register a source of truth (with reference image)
    r = client.post(
        "/sources",
        data={
            "name": "Flagship Claim", "type": "claim",
            "description": "Approved marketing claim",
            "label": "Original Promise", "claim_text": "Lasts All Day",
            "region": "EU",
        },
        files={"reference": ("ref.png", _png((10, 20, 30)), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    page = client.get("/sources").text
    assert "Flagship Claim" in page

    # register an asset that visually derives from the SoT reference
    r = client.post(
        "/assets",
        data={
            "name": "Homepage Hero", "asset_type": "hero_ad",
            "campaign": "Launch", "on_image_text": "Lasts All Day",
        },
        files={"file": ("hero.png", _png((10, 20, 30)), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    # a clearly unrelated asset (should end up safe)
    r = client.post(
        "/assets",
        data={"name": "Office Notice", "asset_type": "other", "on_image_text": "Wi-Fi password"},
        files={"file": ("notice.png", _png((200, 200, 200)), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text

    # find the source item id from the registry page's version form action
    import re

    m = re.search(r"/sources/([0-9a-f-]+)/versions", client.get("/sources").text)
    assert m, "source item id not found in UI"
    return m.group(1)


def test_new_company_full_onboarding_and_recall(client):
    _signup(client, "founder@newco.example", "NewCo")
    item_id = _onboard_company(client)

    assets_page = client.get("/assets").text
    assert "Homepage Hero" in assets_page and "Office Notice" in assets_page

    # add a new approved version (the truth change)
    r = client.post(
        f"/sources/{item_id}/versions",
        data={"label": "New Promise", "claim_text": "Lasts 12 Hours"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # the create-recall form is reachable and lists our source
    new_recall_page = client.get("/recalls/new").text
    assert "Flagship Claim" in new_recall_page

    # run a recall through the product (POST /recalls) using the two versions
    # of our source item
    from sqlalchemy import select

    from rusted_recall.db import session_scope
    from rusted_recall.models import SourceOfTruthVersion

    with session_scope() as s:
        versions = list(
            s.execute(
                select(SourceOfTruthVersion)
                .where(SourceOfTruthVersion.item_id == item_id)
                .order_by(SourceOfTruthVersion.version)
            ).scalars().all()
        )
        old_v, new_v = versions[0].id, versions[-1].id

    r = client.post(
        "/recalls",
        data={
            "source_item_id": item_id,
            "old_version_id": old_v,
            "new_version_id": new_v,
            "reason": "Claim updated",
            "severity": "high",
            "markets": "EU",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    recall_url = r.headers["location"]
    detail = client.get(recall_url).text
    # impact analysis ran and classified our assets through the same engine
    assert "Homepage Hero" in detail
    assert "safe" in detail.lower()


def test_workspace_isolation(client):
    # Company A onboards data and runs a recall
    _signup(client, "a@a.example", "AlphaCo")
    item_a = _onboard_company(client)
    from sqlalchemy import select

    from rusted_recall.db import session_scope
    from rusted_recall.models import SourceOfTruthVersion

    client.post(
        f"/sources/{item_a}/versions",
        data={"label": "A2", "claim_text": "Changed A"},
        follow_redirects=False,
    )
    with session_scope() as s:
        vs = list(s.execute(
            select(SourceOfTruthVersion).where(SourceOfTruthVersion.item_id == item_a)
            .order_by(SourceOfTruthVersion.version)
        ).scalars().all())
    r = client.post("/recalls", data={
        "source_item_id": item_a, "old_version_id": vs[0].id,
        "new_version_id": vs[-1].id, "reason": "x", "severity": "high", "markets": "",
    }, follow_redirects=False)
    recall_a = r.headers["location"].rsplit("/", 1)[-1]

    # Company B logs in fresh
    _signup(client, "b@b.example", "BetaCo")

    # B cannot see A's assets/sources
    assert "Flagship Claim" not in client.get("/sources").text
    assert "Homepage Hero" not in client.get("/assets").text

    # B cannot open A's recall (isolation) -> 404
    assert client.get(f"/recalls/{recall_a}", follow_redirects=False).status_code == 404
    assert client.get(f"/api/recalls/{recall_a}/status").status_code == 404
    assert client.post(f"/recalls/{recall_a}/repair", follow_redirects=False).status_code == 404


def test_create_routes_require_login(client):
    client.cookies.clear()
    r = client.post(
        "/sources",
        data={"name": "x", "label": "l", "claim_text": "c"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_deterministic_derivation_method_is_persisted(client):
    """A company can declare a crop/resize derivation through the UI so the
    child reconciles natively (zero provider calls) — the deterministic-rebuild
    innovation must be reachable without editing source or SQL."""
    from sqlalchemy import select

    from rusted_recall import db
    from rusted_recall.models import Asset

    _signup(client, "deriv@co.example", "DerivCo")
    r = client.post(
        "/assets",
        data={"name": "Master Banner", "asset_type": "hero_ad", "on_image_text": "Hi"},
        files={"file": ("master.png", _png((10, 20, 30), (400, 300)), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    with db.session_scope() as s:
        master = s.execute(
            select(Asset).where(Asset.name == "Master Banner")
        ).scalar_one()
        master_id = master.id

    r = client.post(
        "/assets",
        data={
            "name": "Square Crop", "asset_type": "hero_ad",
            "parent_asset_id": master_id, "derivation_method": "crop",
        },
        files={"file": ("crop.png", _png((10, 20, 30), (200, 200)), "image/png")},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    with db.session_scope() as s:
        child = s.execute(
            select(Asset).where(Asset.name == "Square Crop")
        ).scalar_one()
        assert child.parent_asset_id == master_id
        assert child.derivation_method == "crop"


def test_invalid_asset_upload_rejected(client):
    _signup(client, "v@v.example", "ValidCo")
    r = client.post(
        "/assets",
        data={"name": "bad", "asset_type": "other"},
        files={"file": ("bad.txt", b"not an image", "text/plain")},
        follow_redirects=False,
    )
    assert r.status_code == 400
