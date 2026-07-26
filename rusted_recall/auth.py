"""Authentication and tenancy helpers (spec sections 26-28).

Passwords are hashed with PBKDF2-HMAC-SHA256 (a standard KDF from the Python
standard library — no hand-rolled cryptography, spec section 27). Sessions are
server-side: an opaque high-entropy token is issued to the client in a secure,
http-only cookie and only its SHA-256 hash is stored. For a hosted deployment a
managed identity provider (Auth0/Clerk/Cognito) can be swapped in behind
:func:`authenticate` without touching call sites.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rusted_recall.models import (
    Organisation,
    OrganisationMembership,
    User,
    UserSession,
    Workspace,
)

SESSION_COOKIE = "rr_session"
SESSION_TTL = timedelta(days=14)
_PBKDF2_ROUNDS = 240_000


class AuthError(Exception):
    """Raised on signup/login failure."""


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "org"


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise AuthError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_hex, hash_hex = encoded.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds_s)
    )
    return hmac.compare_digest(dk.hex(), hash_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    n = 1
    while session.execute(
        select(Organisation).where(Organisation.slug == slug)
    ).scalar_one_or_none() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def sign_up(
    session: Session,
    *,
    email: str,
    password: str,
    name: str = "",
    org_name: str = "",
) -> tuple[User, Organisation]:
    """Create a user, their organisation, and an owner membership."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("a valid email is required")
    existing = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise AuthError("an account with this email already exists")

    user = User(email=email, name=name, password_hash=hash_password(password))
    session.add(user)
    session.flush()

    org = Organisation(
        name=org_name or (name or email.split("@")[0]),
        slug=_unique_slug(session, _slugify(org_name or email.split("@")[0])),
    )
    session.add(org)
    session.flush()
    session.add(
        OrganisationMembership(org_id=org.id, user_id=user.id, role="owner")
    )
    session.flush()
    return user, org


def authenticate(session: Session, *, email: str, password: str) -> User:
    user = session.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("invalid email or password")
    return user


def create_session(session: Session, user: User) -> str:
    """Issue a session; returns the raw token to set as a cookie."""
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        )
    )
    session.flush()
    return token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.execute(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        session.delete(row)
        return None
    return session.get(User, row.user_id)


def destroy_session(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.execute(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)


def primary_org_for_user(session: Session, user: User) -> Organisation | None:
    membership = session.execute(
        select(OrganisationMembership)
        .where(OrganisationMembership.user_id == user.id)
        .order_by(OrganisationMembership.created_at)
    ).scalars().first()
    if membership is None:
        return None
    return session.get(Organisation, membership.org_id)


def user_can_access_org(session: Session, user: User, org_id: str) -> bool:
    membership = session.execute(
        select(OrganisationMembership).where(
            OrganisationMembership.user_id == user.id,
            OrganisationMembership.org_id == org_id,
        )
    ).scalar_one_or_none()
    return membership is not None


def user_can_access_workspace(session: Session, user: User, workspace: Workspace) -> bool:
    """Tenant isolation gate (spec section 28). A workspace with no org (legacy
    demo data) is treated as shared/demo and readable by any authenticated user."""
    if workspace.org_id is None:
        return True
    return user_can_access_org(session, user, workspace.org_id)
