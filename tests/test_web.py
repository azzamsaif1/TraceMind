"""Web smoke test: seed via production services, then exercise the UI + APIs."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


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

    from rusted_recall.demo import lumaleaf

    result = lumaleaf.seed(config.get_settings())
    assert result["status"] == "seeded"

    with TestClient(webapp.app) as c:
        c._recall_id = result["recall_id"]  # type: ignore[attr-defined]
        yield c

    db.reset_engine()
    config.get_settings.cache_clear()


def test_health_and_ready(client):
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"


def test_core_screens_render(client):
    for path in ["/", "/assets", "/sources", "/recalls/new", "/diagnostics"]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "Rusted Recall" in resp.text


def test_recall_detail_and_impact(client):
    rid = client._recall_id
    resp = client.get(f"/recalls/{rid}")
    assert resp.status_code == 200
    assert "Interactive Impact Map" in resp.text
    assert "directly affected" in resp.text.replace("_", " ")


def test_technical_evidence_page(client):
    rid = client._recall_id
    resp = client.get(f"/recalls/{rid}/evidence")
    assert resp.status_code == 200
    assert "ChangeSet" in resp.text
    assert "Minimal repair plan" in resp.text


def test_history_and_account_pages(client):
    assert client.get("/history").status_code == 200
    # account requires login -> redirect
    r = client.get("/account", follow_redirects=False)
    assert r.status_code == 303


def test_status_api_and_report(client):
    rid = client._recall_id
    status = client.get(f"/api/recalls/{rid}/status").json()
    assert "recall_status" in status
    report = client.get(f"/recalls/{rid}/report.json")
    assert report.status_code == 200
    body = report.json()
    assert body["totals"]["total_assets_scanned"] >= 1


def test_object_serving(client):
    # previews were created during seed; the assets page references them
    page = client.get("/assets").text
    assert "/obj?key=" in page


def test_repair_disabled_without_provider_shows_banner(client):
    rid = client._recall_id
    page = client.get(f"/recalls/{rid}").text
    assert "Repairs disabled" in page
