# Operations

## Configuration

All configuration is environment-driven (see `.env.example`). Key variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_ENV` | `development` \| `production` \| `test` | `development` |
| `DATABASE_URL` | SQLAlchemy URL. PostgreSQL in prod; SQLite allowed in dev/test. | local postgres |
| `STORAGE_BACKEND` | `auto` \| `b2` \| `local` | `auto` |
| `B2_KEY_ID` / `B2_APP_KEY` / `B2_BUCKET_NAME` | Backblaze B2 S3-compatible credentials | — |
| `B2_S3_ENDPOINT` / `B2_REGION` | B2 S3 endpoint + region | — / `us-west-004` |
| `GMICLOUD_API_KEY` | GMI Cloud image provider key | — |
| `GMICLOUD_BASE_URL` / `GMICLOUD_MODEL` | GMI Cloud endpoint + model | api.gmi-serving.com / gmi/seedream-3.0 |
| `GENBLAZE_ENABLED` | enable Genblaze pipeline orchestration | `false` |
| `DEMO_MAX_REPAIRS_PER_RECALL` | paid-call cap per recall | `3` |

`STORAGE_BACKEND=auto` uses B2 when fully configured, otherwise local
development storage — but **local storage is refused when `APP_ENV=production`**
so a misconfigured deploy fails loudly instead of silently writing to disk.

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

# dev DB + local storage, no external services required
export APP_ENV=development STORAGE_BACKEND=local \
       DATABASE_URL="sqlite:///./rusted_recall.db"

python -m rusted_recall.demo.lumaleaf     # seed the LumaLeaf campaign
uvicorn rusted_recall.web.app:app --reload
```

Open http://localhost:8000.

## Running with Docker Compose (PostgreSQL)

```bash
cp .env.example .env   # fill in real values to enable B2 + repairs
docker compose up --build
```

The `web` container runs `alembic upgrade head` before serving.

## Migrations

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

`alembic/env.py` reads `DATABASE_URL` and uses the application metadata, so
autogenerate stays in sync with `rusted_recall/models.py`.

## Health & readiness

- `GET /healthz` — liveness (always `{"status":"ok"}` when the process is up).
- `GET /readyz` — checks database connectivity and reports storage + provider
  status; returns `503` when the database is unreachable.
- `GET /diagnostics` — HTML panel with provider/storage/OCR capability and the
  scoring weights & thresholds. No secrets are shown.

## Observability

Logs are structured JSON with a per-request `request_id` and, where relevant,
`workspace_id`, `recall_id`, `asset_id`, `job_id`, `provider`, and `operation`.
Secret-bearing fields are redacted.

## Repair jobs

Repairs run on a background worker (`rusted_recall/jobs.py`). Job state lives in
the `repair_jobs` table (`queued → running → completed | failed |
requires_review`) and is polled by the UI. For horizontal scaling, replace the
in-process runner with an external queue consuming the same `RepairJob` rows.

## Failure behaviour

- No provider configured → jobs recorded as `failed` with
  `error_category=authentication`; plan and inputs preserved for retry.
- Provider errors are classified; only retryable classes retry (bounded).
- Validation failures mark the repaired version `requires_review` rather than
  silently publishing it.
