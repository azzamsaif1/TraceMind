# Testing instructions for judges

## Fastest path (no credentials, ~1 minute)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
export APP_ENV=development STORAGE_BACKEND=local \
       DATABASE_URL="sqlite:///./rusted_recall.db"
python -m rusted_recall.demo.lumaleaf
uvicorn rusted_recall.web.app:app
```

Open <http://localhost:8000> and:

1. **Command Center** — see the seeded LumaLeaf workspace and the pending recall.
2. **Source of Truth** — the product package with claim v1 "24-Hour Vitality"
   and v2 "Daily Botanical Blend".
3. **Asset Registry** — ingested assets with real SHA-256 / pHash / dimensions.
4. Open the recall → **Interactive Impact Map**, then the **Review Queue** with
   explainable per-asset scores (the unrelated poster is `safe`; the master pack
   is `directly_affected`).
5. **Download report** as JSON/CSV/HTML/PDF.

Repairs are **disabled** in this mode (no provider) — the UI says so and shows
no fake output.

## Full path with real repairs

Set real credentials and use Docker Compose (PostgreSQL):

```bash
cp .env.example .env         # add B2 + GMICLOUD_API_KEY, set GENBLAZE_ENABLED=true
docker compose up --build
```

Then in the recall view click **Run repairs** and watch job state move
`queued → running → completed`, with real repaired versions and manifests in the
Before/After gallery.

## Automated tests

```bash
ruff check rusted_recall tests
pytest
RUN_INTEGRATION=1 pytest tests/test_integration_smoke.py   # needs real creds
```

## Health

- `GET /healthz`, `GET /readyz`, `GET /diagnostics`.
