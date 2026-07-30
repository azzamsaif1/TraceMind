# Production Journey Proof

Target public app: `https://rusted-recall.onrender.com`

## Topology (code + config in this branch)
```
        enqueue (durable)                claim (SKIP LOCKED)
 WEB  ───────────────────►  Postgres  ◄───────────────────  WORKER
 (uvicorn)              repair_queue_items              (python -m rusted_recall.worker)
```
- `render.yaml` declares a `web` service, a separate `worker` service, and a
  managed Postgres — all sharing `DATABASE_URL`. Web runs migrations and serves;
  web sets `RUN_INLINE_WORKER=false` so only the dedicated worker executes.
- Single-service fallback: with `RUN_INLINE_WORKER=true` (default) the web dyno
  drains its own durable queue on a background thread — functional today without
  a second service, just not horizontally scaled.

## What is PROVEN now (executable)
- **Migrations on production dialect:** `alembic upgrade head` applies the full
  chain (initial → 15fabd319801 → 2b7c9d1e4f10) on Postgres 16; downgrade and
  re-upgrade of the new revision verified.
- **Durable persistence + restart safety:** `tests/test_worker_queue.py`.
- **Atomic concurrent claim on real Postgres:** `scripts/pg_claim_proof.py`
  → `items=5 successful_claims=5 unique=5 claimed_rows=5 threads=10` → PASS.
- **Real B2:** `evidence/B2_PROOF.json` (`result: PASS`).
- **Diagnostics** separates *configured* vs *verified working* and shows worker
  mode + live queue depth (`queued/claimed/done/failed`).

## What is BLOCKED (needs owner)
- **Deploy of THIS branch** to the public URL — merge the PR; Render redeploys.
- **Dedicated worker service on Render** — apply `render.yaml` as a Blueprint and
  set web `RUN_INLINE_WORKER=false`.
- **Real provider generation** — add GMI credits (HTTP 402 today).
- **Incognito judge + customer signup on the deployed branch** — re-run after the
  above; the same flows already pass locally (`tests/test_web*.py`, prior browser
  E2E on PR #3).

No local SQLite/local-storage result is presented as production evidence; the
B2 and Postgres proofs above use real B2 and a real Postgres server.
