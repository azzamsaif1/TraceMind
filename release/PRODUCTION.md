# Production deployment

## Targets

Any host that can run the container and reach a managed Postgres and B2. A public HTTPS
deployment must provide:

- a stable URL;
- managed secrets (never in the image);
- a managed production database (`DATABASE_URL`);
- durable jobs (the in-process worker is fine for a single instance; use an external queue
  for horizontal scale);
- logs and a health endpoint (`/healthz`, `/readyz`);
- migrations applied on release (`alembic upgrade head`);
- **no developer password wall** blocking judges (the demo workspace is public read-only).

## Release steps

```bash
alembic upgrade head
uvicorn rusted_recall.web.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Set `APP_ENV=production` to enable secure cookies and suppress stack traces.

## Post-deploy smoke test (incognito)

1. Open the production URL in a private window.
2. Confirm the public LumaLeaf demo loads and the seeded recall renders impact + evidence.
3. Confirm `/healthz` and `/readyz` are green.
4. Sign up a throwaway account; confirm you get an isolated workspace and cannot see other
   tenants' data.

## Cost/quota controls

`DEMO_MAX_ASSETS_PER_RECALL` and `DEMO_MAX_REPAIRS_PER_RECALL` cap provider spend in public
mode. Tune per plan.
