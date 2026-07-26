# How we built it

Python 3.12 + FastAPI + Jinja2 for the app; SQLAlchemy 2 + Alembic over PostgreSQL
(SQLite for dev/tests). Backblaze B2 via the S3-compatible API (boto3) with retry/backoff
and read-back verification is the media system of record. Repairs run through the Genblaze
pipeline boundary with GMI Cloud as the image provider.

The invention is four cooperating modules: `changeset.py` (typed change semantics),
`propagation.py` (the Change Propagation Engine over the dependency graph), `planner.py`
(the Minimal Repair Planner), and immutable provenance in B2. Auth is PBKDF2-HMAC-SHA256
with server-side opaque sessions. Quality is enforced with Ruff, mypy, and pytest, plus
anti-regression gates that keep the demo running the same code as production.
