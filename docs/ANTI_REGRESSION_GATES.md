# Anti-regression gates

These gates keep Rusted Recall honest and prevent a slide back into the prototype's
"demo-first, fabricated output" failure mode (see PREVIOUS_PROJECT_POSTMORTEM.md).

## Honesty gates (must always hold)

1. **No fabricated output in production paths.** No hardcoded recall counts, affected
   assets, impact graphs, confidence scores, cost savings, hashes, or provenance. Mocks
   are permitted **only** inside `tests/`.
2. **Real system of record.** Originals are written once to B2 and never overwritten;
   repairs create new immutable `AssetVersion`s with manifests; the audit log is
   append-only.
3. **Honest failure.** When a provider or B2 is not configured, the operation is disabled
   with a clear error and inputs/plans are preserved — never a fake success.
4. **One code path.** The LumaLeaf demo seeds through the same production services
   (`services.ingest_asset`, `create_recall_event`, `run_impact_analysis`,
   `approve_and_repair`) as a real tenant — no demo-only branch.
5. **Computed, not guessed.** Impact scores come from the weighted evidence model;
   repair savings come from the Minimal Repair Planner over the real graph.

## Tenancy gates

6. Every tenant-scoped view resolves the workspace from the authenticated user's
   organisation; cross-organisation access is not possible via asset/source/recall/report
   IDs. Anonymous visitors only ever see the shared demo workspace.

## Automated quality gates (CI)

Run before every merge:

```bash
ruff check rusted_recall tests alembic
mypy rusted_recall
pytest
```

Test coverage that enforces the gates above:

- `tests/test_changeset.py` — ChangeSet semantics, propagation eligibility, inferred-change confidence.
- `tests/test_propagation.py` — edge-type filtering, cycle safety, explicit-edge preservation, aggregation.
- `tests/test_planner.py` — deterministic rebuild selection and operations-avoided math.
- `tests/test_auth_tenancy.py` + `tests/test_web_auth.py` — password hashing, sessions, cross-org isolation, protected routes.
- `tests/test_end_to_end.py` + `tests/test_usage_changeset_integration.py` — full recall flow, immutable lineage, honest no-provider behaviour, usage metering.

## Credential gates

7. No secrets in source, logs, reports, screenshots, or the browser bundle. Real-cred
   smoke tests are skipped unless credentials are present in the environment.
