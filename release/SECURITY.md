# Security (release)

See also `docs/SECURITY.md`.

## Principles

- **Server-side secrets only.** Nothing sensitive reaches the browser bundle, logs,
  reports, or screenshots.
- **Least privilege.** B2 keys scoped to a single private bucket; provider keys scoped to
  the needed operations.
- **Tenant isolation.** All tenant data is resolved from the authenticated user's
  organisation; cross-org access via any ID is blocked.
- **Uploads.** MIME + size validation, filename sanitization, path-traversal prevention.
- **Sessions.** Opaque tokens; only the SHA-256 hash is persisted; secure + httponly
  cookies in production; 14-day expiry.
- **Transport.** HTTPS required in production; secure-cookie flag keyed to `APP_ENV`.
- **No stack traces** are exposed to end users in production.

## Passwords

PBKDF2-HMAC-SHA256 with per-user salt (standard library, no external dependency). Minimum
length enforced.

## Supply chain

- Prefer dependency versions published ≥7 days ago; avoid floating ranges.
- Run secret scanning and dependency audit in CI.

## Known debt (owner action)

Leaked credentials remain in git history (commits `001130e`, `ba6e9f8`, `2aed6b3`). The
owner must rotate/revoke the B2 and GMI Cloud credentials and decide whether to authorize a
destructive history scrub.
