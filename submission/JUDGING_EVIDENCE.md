# Judging evidence

## Real use of Backblaze B2
Media system of record; originals immutable; manifests, plans, snapshots, and reports all in
B2; read-back verified. See `submission/DEVPOST_B2_USAGE.md` and
`rusted_recall/storage/`.

## Real use of Genblaze + GMI Cloud
Repairs execute through the Genblaze boundary with GMI Cloud; honest failure without creds.
See `submission/DEVPOST_GENBLAZE_USAGE.md` and `rusted_recall/providers/`.

## Technical depth / originality
Typed ChangeSet semantics + change-aware propagation engine + minimal-repair planner +
immutable provenance. See `docs/INNOVATION.md`,
`rusted_recall/{changeset,propagation,planner}.py`.

## Explainability
Every impact carries score components, a causal explanation, and a propagation reason,
surfaced on `/recalls/{id}/evidence`.

## Honesty / no fabrication
Anti-regression gates + tests; the demo runs the production code path; missing integrations
disable operations. See `docs/ANTI_REGRESSION_GATES.md`.

## Completeness as a product
Multi-tenant SaaS: auth, organisations, workspaces, isolation, onboarding, usage metering,
account views, and exportable reports.

## Reproducibility
`cp .env.example .env && docker compose up --build`; migrations via Alembic; green Ruff +
mypy + pytest.
