import pytest

from rusted_recall import auth, services
from rusted_recall.db import create_all, reset_engine, session_scope


@pytest.fixture(autouse=True)
def _sqlite_db(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "storage"))
    from rusted_recall.config import get_settings

    get_settings.cache_clear()
    reset_engine()
    create_all()
    yield
    reset_engine()
    get_settings.cache_clear()


def test_password_hash_roundtrip():
    encoded = auth.hash_password("supersecret")
    assert encoded.startswith("pbkdf2_sha256$")
    assert auth.verify_password("supersecret", encoded)
    assert not auth.verify_password("wrong", encoded)


def test_short_password_rejected():
    with pytest.raises(auth.AuthError):
        auth.hash_password("short")


def test_sign_up_creates_owner_membership():
    with session_scope() as s:
        user, org = auth.sign_up(
            s, email="a@example.com", password="password123", name="A", org_name="Acme"
        )
        assert user.email == "a@example.com"
        assert auth.user_can_access_org(s, user, org.id)
        primary = auth.primary_org_for_user(s, user)
        assert primary is not None and primary.id == org.id


def test_duplicate_email_rejected():
    with session_scope() as s:
        auth.sign_up(s, email="dup@example.com", password="password123")
    with session_scope() as s, pytest.raises(auth.AuthError):
        auth.sign_up(s, email="dup@example.com", password="password123")


def test_authenticate_and_session_lifecycle():
    with session_scope() as s:
        auth.sign_up(s, email="b@example.com", password="password123")
    with session_scope() as s:
        user = auth.authenticate(s, email="b@example.com", password="password123")
        token = auth.create_session(s, user)
    with session_scope() as s:
        recovered = auth.user_for_token(s, token)
        assert recovered is not None and recovered.email == "b@example.com"
        auth.destroy_session(s, token)
    with session_scope() as s:
        assert auth.user_for_token(s, token) is None


def test_authenticate_wrong_password():
    with session_scope() as s:
        auth.sign_up(s, email="c@example.com", password="password123")
    with session_scope() as s, pytest.raises(auth.AuthError):
        auth.authenticate(s, email="c@example.com", password="nope")


def test_tenant_isolation_across_two_orgs():
    with session_scope() as s:
        user_a, org_a = auth.sign_up(s, email="oa@example.com", password="password123")
        user_b, org_b = auth.sign_up(s, email="ob@example.com", password="password123")
        ws_a = services.create_workspace(s, "A workspace", org_id=org_a.id)
        ws_b = services.create_workspace(s, "B workspace", org_id=org_b.id)

        # user A can reach their own workspace, not org B's.
        assert auth.user_can_access_workspace(s, user_a, ws_a)
        assert not auth.user_can_access_workspace(s, user_a, ws_b)
        assert auth.user_can_access_workspace(s, user_b, ws_b)
        assert not auth.user_can_access_workspace(s, user_b, ws_a)
