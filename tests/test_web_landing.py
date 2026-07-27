"""Homepage + judge-entry routes (directive sections 5, 6, 11, 23)."""
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
    with TestClient(webapp.app) as c:
        yield c
    db.reset_engine()
    config.get_settings.cache_clear()


def test_landing_is_product_page_not_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Change one source." in r.text
    assert "Run Live Recall" in r.text
    assert "Start Free" in r.text


def test_run_live_enters_golden_recall(client):
    r = client.get("/run-live", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/recalls/")
    # the target recall renders
    assert client.get(r.headers["location"]).status_code == 200


def test_generalisation_enters_northstar_recall(client):
    r = client.get("/generalisation", follow_redirects=False)
    assert r.status_code == 303
    target = r.headers["location"]
    assert target.startswith("/recalls/")
    page = client.get(target).text
    # Northstar assets, not LumaLeaf ones.
    assert "Northstar" in page or "Packaging Master" in page


def test_run_live_is_idempotent(client):
    first = client.get("/run-live", follow_redirects=False).headers["location"]
    second = client.get("/run-live", follow_redirects=False).headers["location"]
    assert first == second


def test_submission_evidence_lists_all_four_criteria(client):
    r = client.get("/submission-evidence")
    assert r.status_code == 200
    for heading in [
        "Real-World Utility",
        "Production Readiness",
        "B2 Storage and Data Orchestration",
        "Genblaze",
    ]:
        assert heading in r.text


def test_diagnostics_exposes_build_and_health(client):
    r = client.get("/diagnostics")
    assert r.status_code == 200
    assert "Commit SHA" in r.text
    assert "Worker" in r.text
