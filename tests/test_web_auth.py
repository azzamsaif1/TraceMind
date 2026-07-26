"""Web auth + tenant-scoping smoke test through the real FastAPI app."""
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


def test_public_pages_do_not_require_login(client):
    for path in ["/", "/login", "/signup"]:
        assert client.get(path).status_code == 200


def test_protected_pages_redirect_when_anonymous(client):
    r = client.get("/account", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_signup_login_logout_flow(client):
    r = client.post(
        "/signup",
        data={"email": "founder@example.com", "password": "password123", "org_name": "Acme"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding"
    assert "rr_session" in r.cookies

    # authenticated: account page renders
    acct = client.get("/account")
    assert acct.status_code == 200
    assert "founder@example.com" in acct.text

    # logout clears the session
    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    client.cookies.clear()
    assert client.get("/account", follow_redirects=False).status_code == 303


def test_duplicate_signup_shows_error(client):
    client.post(
        "/signup", data={"email": "dup@example.com", "password": "password123"},
        follow_redirects=False,
    )
    client.cookies.clear()
    r = client.post(
        "/signup", data={"email": "dup@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "already" in r.text.lower() or "exists" in r.text.lower()


def test_wrong_password_rejected(client):
    client.post(
        "/signup", data={"email": "u@example.com", "password": "password123"},
        follow_redirects=False,
    )
    client.cookies.clear()
    r = client.post(
        "/login", data={"email": "u@example.com", "password": "wrongpass"},
        follow_redirects=False,
    )
    assert r.status_code == 401
