# Install (self-host)

Rusted Recall is self-hostable from the repository.

## Requirements

- Python 3.12
- PostgreSQL 14+ (production) — SQLite is used automatically for local/dev and tests
- Optional: Docker + Docker Compose

## Steps

```bash
git clone https://github.com/azzamsaif1/TraceMind.git
cd TraceMind
cp .env.example .env
# edit .env: set DATABASE_URL, STORAGE_BACKEND, and (for repairs) B2 + GMI/Genblaze creds
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn rusted_recall.web.app:app --host 0.0.0.0 --port 8000
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

This starts the app and a Postgres service. Migrations run on startup.

## Verify

- `GET /healthz` → `{"status": "ok"}`
- `GET /readyz` → database + storage checks
- `GET /diagnostics` → provider/storage configuration (no secrets shown)

See `release/ENVIRONMENT.md` for every configuration variable.
