# Environment configuration

All secrets are server-side only. Never commit `.env`. `.env.example` contains placeholders.

| Variable | Purpose | Default (dev) |
|---|---|---|
| `APP_ENV` | `development` or `production` (controls secure cookies, error verbosity) | `development` |
| `DATABASE_URL` | SQLAlchemy URL. Postgres in prod, SQLite in dev/tests | `sqlite:///./rusted_recall.db` |
| `STORAGE_BACKEND` | `b2` or `local` | `local` |
| `LOCAL_STORAGE_DIR` | Directory for local object storage (dev only) | `./_storage` |
| `B2_KEY_ID` | Backblaze B2 application key ID | *(unset)* |
| `B2_APP_KEY` | Backblaze B2 application key | *(unset)* |
| `B2_BUCKET_NAME` | B2 bucket (must not be public-write) | *(unset)* |
| `B2_ENDPOINT_URL` | S3-compatible endpoint for the bucket region | *(unset)* |
| `B2_REGION` | Bucket region | *(unset)* |
| `GENBLAZE_*` | Genblaze pipeline configuration | *(unset)* |
| `GMICLOUD_API_KEY` | GMI Cloud provider key (image generation/editing) | *(unset)* |
| `DEMO_MAX_ASSETS_PER_RECALL` | Cost/quota guard for public mode | `25` |
| `DEMO_MAX_REPAIRS_PER_RECALL` | Cost/quota guard for public mode | `3` |

## Behaviour when unset

- No `STORAGE_BACKEND=b2` creds → local storage is used (dev) or the app reports storage is
  not ready (prod `/readyz`).
- No provider/Genblaze creds → repair operations are disabled with an honest error; all
  other features work.
