# Quickstart

Run Rusted Recall locally and see the full recall in under 5 minutes.

```bash
cp .env.example .env          # local defaults: SQLite + local storage, no secrets needed
docker compose up --build     # starts the app + Postgres
```

Then open http://localhost:8000

- **Browse the public demo** — the LumaLeaf Botanical Sparkling Water campaign is seeded
  through the real production services. No login required (judge-friendly).
- Open the seeded recall → **Impact Map**, **Technical Evidence** (`/recalls/{id}/evidence`),
  **Repair Operations**, **Before/After**, and the **Audit Report** (JSON/CSV/HTML/PDF).
- Create your own account at `/signup` to get an isolated organisation + workspace.

## Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m rusted_recall.demo.lumaleaf   # optional: seed the demo
uvicorn rusted_recall.web.app:app --reload
```

## Repairs

Real generative repairs require a provider (GMI Cloud) + Genblaze configuration and a B2
bucket — see `release/BACKBLAZE.md` and `release/GENBLAZE.md`. Without them, repair is
disabled with a clear message and nothing is fabricated; the rest of the product
(ingestion, evidence, impact, planning, reports) works fully.
