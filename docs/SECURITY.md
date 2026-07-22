# Security

## Secrets

- All credentials are read from the environment (`.env` in development, real
  environment variables in production). `.env` is git-ignored; only
  `.env.example` (placeholders) is committed.
- No secret is ever logged. The structured logger redacts any field whose name
  contains `key`, `token`, `secret`, `password`, or `authorization`
  (`rusted_recall/logging_setup.py`).
- The B2 application key and GMI Cloud API key are used server-side only. They
  are never sent to the browser and never embedded in manifests or reports.

## ⚠️ Leaked credentials in git history

The pre-existing `.env.example` in this repository committed **real-looking**
credentials (`B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET_NAME`, `GMICLOUD_API_KEY`)
in commits `001130e`, `ba6e9f8`, and `2aed6b3`. The working copy has been
sanitized, but the values remain in history.

**Required human action (cannot be done by the agent):**

1. **Revoke/rotate** the exposed Backblaze B2 application key and GMI Cloud API
   key immediately — treat them as compromised.
2. Decide whether to **rewrite git history** (e.g. `git filter-repo` or BFG)
   to purge the values, followed by a force-push. This is destructive and must
   be coordinated with everyone who has cloned the repo.

Until rotation is complete, assume the exposed keys are public.

## Storage integrity

- Original uploads are never overwritten. Repairs always create a new immutable
  version under a distinct B2 key.
- Every stored object is read back and its SHA-256 verified after write
  (`B2Storage.put_bytes`).
- Object keys are server-controlled and derived from workspace/asset/version
  IDs; user-supplied filenames are sanitized to prevent path traversal.

## Provider trust boundary

- If a provider is not configured, repairs are **disabled** and reported as
  such. The system never fabricates generated output.
- Provider HTTP errors are classified (auth, quota, rate limit, timeout,
  unavailable, invalid request, safety rejection) and only retryable classes
  are retried, with bounded attempts.

## Demo / judge mode

- `DEMO_MAX_REPAIRS_PER_RECALL` (default 3) caps paid generation calls per
  recall to bound cost when the app is publicly reachable.
- `DEMO_MAX_ASSETS_PER_RECALL` and `DEMO_MAX_CONCURRENT_JOBS` bound analysis and
  job concurrency.
