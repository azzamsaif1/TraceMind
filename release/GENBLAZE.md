# Genblaze + provider setup

Repairs run through the Genblaze pipeline boundary
(`rusted_recall/providers/genblaze.py`) with a real image provider (GMI Cloud) behind it.

## References

- Genblaze: https://github.com/backblaze-labs/genblaze (spec under `libs/spec`)
- Reference pipeline: https://github.com/backblaze-labs/genblaze-gmicloud-pipeline

Pin a known-good Genblaze commit/release in your lockfile; do not invent SDK methods.

## Configure

```bash
GMICLOUD_API_KEY=your-gmi-cloud-key
# plus any GENBLAZE_* pipeline settings your deployment requires
```

## Honest failure

If the provider key is missing or invalid, repair jobs fail with
`error_category = "authentication"` (or `provider_unavailable` when all providers are
exhausted). Inputs and the deterministic repair plan are preserved; **no fake output is
ever produced.** A generation smoke test (`tests/test_integration_smoke.py`) is skipped
unless real credentials are present.

## Determinism & idempotency

Each repair plan carries an idempotency key (SHA-256 over recall/asset/version/provider/
model/canonical operation params) so retries do not double-generate.
